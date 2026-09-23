import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { ReportView } from "@/components/reports/report-view";
import type { AnalysisReport } from "@/lib/api";
import fixtures from "./fixtures/reports.json";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

const reports = fixtures as unknown as Record<string, AnalysisReport>;

describe("ReportView", () => {
  it("labels fixtures and displays exact SHAs with the saved recommendation", () => {
    render(<ReportView report={reports.safe} />);
    expect(screen.getByText("Fixture data")).toBeInTheDocument();
    expect(screen.getByText(reports.safe.head_sha)).toBeInTheDocument();
    expect(screen.getByText(reports.safe.base_sha)).toBeInTheDocument();
    expect(
      screen.getByText("GO", { selector: ".recommendation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a probability of success/),
    ).toBeInTheDocument();
  });
  it("puts required CI failure in hard blockers with a remediation checklist", () => {
    render(<ReportView report={reports.failed_ci} />);
    const blockers = screen.getByRole("region", { name: "Hard blockers" });
    expect(
      within(blockers).getByText("Required check failed: integration"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("NO GO", { selector: ".recommendation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Fix and rerun integration on the target SHA."),
    ).toBeInTheDocument();
  });
  it("shows low confidence and missing evidence without green approval", () => {
    render(<ReportView report={reports.missing_evidence} />);
    expect(screen.getByText(/Low confidence/)).toBeInTheDocument();
    expect(
      screen.getByText("CAUTION", { selector: ".recommendation" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("GO", { selector: ".recommendation" }),
    ).not.toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "Missing evidence" }),
      ).getByText("No target CI checks found"),
    ).toBeInTheDocument();
  });
  it("opens cited excerpts and locators in an accessible closable dialog", async () => {
    render(<ReportView report={reports.failed_ci} />);
    const button = screen.getAllByRole("button", {
      name: "View evidence: Integration tests · failure",
    })[0];
    await userEvent.click(button);
    const dialog = screen.getByRole("dialog", {
      name: "Integration tests · failure",
    });
    expect(within(dialog).getByText(/conclusion=failure/)).toBeInTheDocument();
    expect(
      within(dialog).getByText("Fixture v1 · checks/integration/attempt/1"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("link", { name: /Open source/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close evidence" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
