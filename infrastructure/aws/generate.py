"""Generate the reviewable CloudFormation template; never contacts AWS."""
import json
from pathlib import Path

ref = lambda name: {"Ref": name}
get = lambda name, attr: {"Fn::GetAtt": [name, attr]}
sub = lambda value: {"Fn::Sub": value}
resources = {}

def resource(name, kind, properties, **extra):
    resources[name] = {"Type": kind, "Properties": properties, **extra}

parameters = {
    "VpcId": {"Type": "AWS::EC2::VPC::Id"},
    "PublicSubnets": {"Type": "List<AWS::EC2::Subnet::Id>", "Description": "Two public ALB subnets in different AZs"},
    "PrivateSubnets": {"Type": "List<AWS::EC2::Subnet::Id>", "Description": "Two private subnets with NAT egress for GitHub/OpenAI"},
    "CertificateArn": {"Type": "String", "Description": "ACM certificate in this region for AppOrigin"},
    "AppOrigin": {"Type": "String", "AllowedPattern": "https://[^/]+", "Description": "HTTPS origin without trailing slash"},
    "BackendImage": {"Type": "String", "Description": "Immutable ECR backend image URI, preferably digest"},
    "FrontendImage": {"Type": "String", "Description": "Immutable ECR frontend URI built with API_INTERNAL_URL=http://api.releasepilot:8000"},
    "ProviderSecretArn": {"Type": "String", "Description": "Secrets Manager JSON: OPENAI_API_KEY, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET, GITHUB_APP_PRIVATE_KEY, DEMO_PASSWORD"},
    "GitHubAppId": {"Type": "String", "Default": ""},
    "GitHubAppSlug": {"Type": "String", "Default": ""},
    "GitHubClientId": {"Type": "String", "Default": ""},
    "DesiredCount": {"Type": "Number", "Default": 0, "AllowedValues": [0, 1], "Description": "Start at zero; run migrations before setting one"},
    "BudgetEmail": {"Type": "String"},
}
resource("Cluster", "AWS::ECS::Cluster", {"ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}]})
resource("Logs", "AWS::Logs::LogGroup", {"RetentionInDays": 14})
resource("Namespace", "AWS::ServiceDiscovery::PrivateDnsNamespace", {"Name": "releasepilot", "Vpc": ref("VpcId")})
resource("AlbSecurityGroup", "AWS::EC2::SecurityGroup", {"GroupDescription": "HTTPS ingress", "VpcId": ref("VpcId"), "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "CidrIp": "0.0.0.0/0"} for p in (80,443)]})
resource("TaskSecurityGroup", "AWS::EC2::SecurityGroup", {"GroupDescription": "Private application services", "VpcId": ref("VpcId"), "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "SourceSecurityGroupId": ref("AlbSecurityGroup")} for p in (3000,8000)]})
for port in (8000,8001,6379):
    resource(f"Internal{port}", "AWS::EC2::SecurityGroupIngress", {"GroupId": ref("TaskSecurityGroup"), "SourceSecurityGroupId": ref("TaskSecurityGroup"), "IpProtocol": "tcp", "FromPort": port, "ToPort": port})
resource("DatabaseSecurityGroup", "AWS::EC2::SecurityGroup", {"VpcId": ref("VpcId"), "GroupDescription": "Postgres from application tasks only", "SecurityGroupIngress": [{"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "SourceSecurityGroupId": ref("TaskSecurityGroup")}]})
resource("DatabaseSubnets", "AWS::RDS::DBSubnetGroup", {"DBSubnetGroupDescription": "Private PostgreSQL", "SubnetIds": ref("PrivateSubnets")})
resource("Database", "AWS::RDS::DBInstance", {"Engine": "postgres", "DBInstanceClass": "db.t4g.micro", "AllocatedStorage": "20", "StorageType": "gp3", "StorageEncrypted": True, "DBName": "releasepilot", "MasterUsername": "releasepilot", "ManageMasterUserPassword": True, "DBSubnetGroupName": ref("DatabaseSubnets"), "VPCSecurityGroups": [ref("DatabaseSecurityGroup")], "PubliclyAccessible": False, "BackupRetentionPeriod": 7, "DeletionProtection": True, "MultiAZ": False}, DeletionPolicy="Snapshot", UpdateReplacePolicy="Snapshot")
resource("Documents", "AWS::S3::Bucket", {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True}, "BucketEncryption": {"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}, "VersioningConfiguration": {"Status": "Enabled"}}, DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
resource("DocumentsPolicy", "AWS::S3::BucketPolicy", {"Bucket": ref("Documents"), "PolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": [get("Documents", "Arn"), sub("${Documents.Arn}/*")], "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]}})
resource("DeadLetters", "AWS::SQS::Queue", {"MessageRetentionPeriod": 1209600, "SqsManagedSseEnabled": True})
resource("Jobs", "AWS::SQS::Queue", {"VisibilityTimeout": 120, "ReceiveMessageWaitTimeSeconds": 20, "MessageRetentionPeriod": 345600, "SqsManagedSseEnabled": True, "RedrivePolicy": {"deadLetterTargetArn": get("DeadLetters", "Arn"), "maxReceiveCount": 8}})
resource("InternalSecret", "AWS::SecretsManager::Secret", {"GenerateSecretString": {"PasswordLength": 64, "ExcludePunctuation": True}})
assume = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
resource("ExecutionRole", "AWS::IAM::Role", {"AssumeRolePolicyDocument": assume, "ManagedPolicyArns": [sub("arn:${AWS::Partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")], "Policies": [{"PolicyName": "ReadApplicationSecrets", "PolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": [ref("ProviderSecretArn"), ref("InternalSecret"), get("Database", "MasterUserSecret.SecretArn")]}]}}]})
for role, actions in {"ApiRole": ["s3:PutObject"], "WorkerRole": ["s3:GetObject"], "McpRole": []}.items():
    statements = []
    if actions:
        statements.append({"Effect": "Allow", "Action": actions, "Resource": sub("${Documents.Arn}/*")})
    if role == "WorkerRole":
        statements.append({"Effect": "Allow", "Action": ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], "Resource": [get("Jobs", "Arn"), get("DeadLetters", "Arn")]})
    props = {"AssumeRolePolicyDocument": assume}
    if statements:
        props["Policies"] = [{"PolicyName": "ApplicationResources", "PolicyDocument": {"Version": "2012-10-17", "Statement": statements}}]
    resource(role, "AWS::IAM::Role", props)
resource("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Scheme": "internet-facing", "Subnets": ref("PublicSubnets"), "SecurityGroups": [ref("AlbSecurityGroup")]})
for name, port, path in [("Frontend",3000,"/login"),("Api",8000,"/health/ready")]:
    resource(f"{name}Target", "AWS::ElasticLoadBalancingV2::TargetGroup", {"VpcId": ref("VpcId"), "Port": port, "Protocol": "HTTP", "TargetType": "ip", "HealthCheckPath": path})
resource("Https", "AWS::ElasticLoadBalancingV2::Listener", {"LoadBalancerArn": ref("Alb"), "Port": 443, "Protocol": "HTTPS", "Certificates": [{"CertificateArn": ref("CertificateArn")}], "DefaultActions": [{"Type": "forward", "TargetGroupArn": ref("FrontendTarget")}], "SslPolicy": "ELBSecurityPolicy-TLS13-1-2-2021-06"})
resource("Http", "AWS::ElasticLoadBalancingV2::Listener", {"LoadBalancerArn": ref("Alb"), "Port": 80, "Protocol": "HTTP", "DefaultActions": [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"}}]})
resource("ApiRouting", "AWS::ElasticLoadBalancingV2::ListenerRule", {"ListenerArn": ref("Https"), "Priority": 1, "Conditions": [{"Field": "path-pattern", "Values": ["/api/v1/*"]}], "Actions": [{"Type": "forward", "TargetGroupArn": ref("ApiTarget")}]})
common = {"ENVIRONMENT": "production", "APP_ORIGIN": ref("AppOrigin"), "COOKIE_SECURE": "true", "DATABASE_HOST": get("Database", "Endpoint.Address"), "DATABASE_SSLMODE": "require", "REDIS_URL": "redis://redis.releasepilot:6379/0", "MCP_URL": "http://mcp.releasepilot:8001/mcp", "OBJECT_BACKEND": "s3", "S3_BUCKET": ref("Documents"), "QUEUE_BACKEND": "sqs", "SQS_QUEUE_URL": ref("Jobs"), "SQS_DLQ_URL": ref("DeadLetters"), "AWS_REGION": ref("AWS::Region"), "GITHUB_APP_ID": ref("GitHubAppId"), "GITHUB_APP_SLUG": ref("GitHubAppSlug"), "GITHUB_CLIENT_ID": ref("GitHubClientId")}
secrets = [{"Name": "INTERNAL_SECRET", "ValueFrom": ref("InternalSecret")}, {"Name": "DATABASE_PASSWORD", "ValueFrom": {"Fn::Join": ["", [get("Database", "MasterUserSecret.SecretArn"), ":password::"]]}}]
for key in ("OPENAI_API_KEY", "GITHUB_CLIENT_SECRET", "GITHUB_WEBHOOK_SECRET", "GITHUB_APP_PRIVATE_KEY", "DEMO_PASSWORD"):
    secrets.append({"Name": key, "ValueFrom": {"Fn::Join": ["", [ref("ProviderSecretArn"), f":{key}::"]]}})
for name, port, command, role in [("api",8000,None,"ApiRole"),("mcp",8001,["uvicorn","app.mcp_tools.server:app","--host","0.0.0.0","--port","8001"],"McpRole"),("worker",None,["python","-m","app.jobs.worker"],"WorkerRole"),("frontend",3000,None,"McpRole"),("redis",6379,["redis-server","--maxmemory","64mb","--maxmemory-policy","allkeys-lru"],"McpRole"),("migration",None,["sh","-c","alembic upgrade head && python -m app.seed"],"McpRole")]:
    title = name.capitalize()
    container = {"Name": name, "Image": "redis:7.4-alpine" if name == "redis" else ref("FrontendImage" if name == "frontend" else "BackendImage"), "Essential": True, "LogConfiguration": {"LogDriver": "awslogs", "Options": {"awslogs-group": ref("Logs"), "awslogs-region": ref("AWS::Region"), "awslogs-stream-prefix": name}}}
    if name not in ("frontend","redis"):
        container["Environment"] = [{"Name": k, "Value": v} for k,v in common.items()]
        container["Secrets"] = secrets
    if command:
        container["Command"] = command
    if port:
        container["PortMappings"] = [{"ContainerPort": port, "Protocol": "tcp"}]
    if name in ("mcp", "worker", "migration"):
        # Override API-specific image health check for non-API roles.
        container["HealthCheck"] = {"Command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8001/health')\"" if name == "mcp" else "python -c 'import os; os.kill(1,0)'"], "Interval": 30, "Timeout": 5, "Retries": 3, "StartPeriod": 30}
    resource(f"{title}Task", "AWS::ECS::TaskDefinition", {"RequiresCompatibilities": ["FARGATE"], "NetworkMode": "awsvpc", "Cpu": "256", "Memory": "512", "ExecutionRoleArn": get("ExecutionRole","Arn"), "TaskRoleArn": get(role,"Arn"), "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"}, "ContainerDefinitions": [container]})
    if name == "migration":
        continue
    resource(f"{title}Discovery", "AWS::ServiceDiscovery::Service", {"Name": name, "NamespaceId": ref("Namespace"), "DnsConfig": {"DnsRecords": [{"Type": "A", "TTL": 10}]}, "HealthCheckCustomConfig": {"FailureThreshold": 1}})
    props = {"Cluster": ref("Cluster"), "LaunchType": "FARGATE", "DesiredCount": ref("DesiredCount"), "TaskDefinition": ref(f"{title}Task"), "NetworkConfiguration": {"AwsvpcConfiguration": {"AssignPublicIp": "DISABLED", "Subnets": ref("PrivateSubnets"), "SecurityGroups": [ref("TaskSecurityGroup")]}}, "ServiceRegistries": [{"RegistryArn": get(f"{title}Discovery","Arn")}], "DeploymentConfiguration": {"DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}}}
    if name in ("api","frontend"):
        props["LoadBalancers"] = [{"ContainerName": name, "ContainerPort": port, "TargetGroupArn": ref(f"{title}Target")}]
        props["HealthCheckGracePeriodSeconds"] = 60
    resource(f"{title}Service", "AWS::ECS::Service", props, DependsOn=["Https","ApiRouting"])
resource("QueueAgeAlarm", "AWS::CloudWatch::Alarm", {"AlarmDescription": "Analysis backlog older than five minutes", "Namespace": "AWS/SQS", "MetricName": "ApproximateAgeOfOldestMessage", "Dimensions": [{"Name": "QueueName", "Value": get("Jobs","QueueName")}], "Statistic": "Maximum", "Period": 60, "EvaluationPeriods": 3, "Threshold": 300, "ComparisonOperator": "GreaterThanThreshold", "TreatMissingData": "notBreaching"})
resource("Budget", "AWS::Budgets::Budget", {"Budget": {"BudgetType": "COST", "TimeUnit": "MONTHLY", "BudgetLimit": {"Amount": 50, "Unit": "USD"}}, "NotificationsWithSubscribers": [{"Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 80, "ThresholdType": "PERCENTAGE"}, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": ref("BudgetEmail")}]}]})
template = {"AWSTemplateFormatVersion": "2010-09-09", "Description": "ReleasePilot non-production deployment. Existing VPC/NAT/ACM required; review costs before deployment.", "Parameters": parameters, "Resources": resources, "Outputs": {"Cluster": {"Value": ref("Cluster")}, "LoadBalancerDNS": {"Value": get("Alb","DNSName")}, "MigrationTask": {"Value": ref("MigrationTask")}, "TaskSecurityGroup": {"Value": ref("TaskSecurityGroup")}, "DocumentsBucket": {"Value": ref("Documents")}, "QueueURL": {"Value": ref("Jobs")}}}
Path(__file__).with_name("stack.json").write_text(json.dumps(template, indent=2)+"\n")
print("Generated stack.json; no AWS resources created.")
