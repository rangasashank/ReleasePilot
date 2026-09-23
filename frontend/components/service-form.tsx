"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const schema = z.object({
  name: z.string().trim().min(1, "Enter a service name").max(100),
  description: z.string().trim().max(500),
});
export type ServiceFields = z.infer<typeof schema>;
export function ServiceForm({
  onSubmit,
  pending,
  error,
}: {
  onSubmit: (data: ServiceFields) => void;
  pending: boolean;
  error?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ServiceFields>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "" },
  });
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="service-form">
      <label htmlFor="service-name">
        Service name <span className="required">*</span>
      </label>
      <input
        id="service-name"
        placeholder="e.g. Checkout API"
        maxLength={100}
        {...register("name")}
        aria-invalid={!!errors.name}
        aria-describedby={errors.name ? "name-error" : "name-hint"}
      />
      {errors.name ? (
        <p id="name-error" className="error" role="alert">
          {errors.name.message}
        </p>
      ) : (
        <p id="name-hint" className="hint">
          The application or service whose releases you’ll review.
        </p>
      )}
      <label htmlFor="description">
        Description <span className="optional">Optional</span>
      </label>
      <textarea
        id="description"
        rows={3}
        maxLength={500}
        placeholder="What does this service do?"
        {...register("description")}
        aria-invalid={!!errors.description}
      />
      {errors.description && (
        <p className="error" role="alert">
          {errors.description.message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="form-footer">
        <span>Connect GitHub from the Connections page.</span>
        <button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create service"}
          <span aria-hidden="true"> →</span>
        </button>
      </div>
    </form>
  );
}
