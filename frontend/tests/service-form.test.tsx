import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ServiceForm } from "@/components/service-form";

describe("ServiceForm", () => {
  it("rejects blank names without sending a request", async () => {
    const submit = vi.fn();
    render(<ServiceForm onSubmit={submit} pending={false} />);
    await userEvent.click(
      screen.getByRole("button", { name: /create service/i }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a service name",
    );
    expect(submit).not.toHaveBeenCalled();
  });
  it("submits only trimmed service fields", async () => {
    const submit = vi.fn();
    render(<ServiceForm onSubmit={submit} pending={false} />);
    fireEvent.change(screen.getByLabelText(/service name/i), {
      target: { value: "  Checkout API  " },
    });
    await userEvent.click(
      screen.getByRole("button", { name: /create service/i }),
    );
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0][0]).toEqual({
      name: "Checkout API",
      description: "",
    });
  });
  it("shows server errors and prevents another submission while pending", () => {
    render(
      <ServiceForm
        onSubmit={vi.fn()}
        pending
        error="A service with that name already exists"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("already exists");
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
