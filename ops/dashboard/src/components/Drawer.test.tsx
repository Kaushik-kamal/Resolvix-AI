import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Drawer } from "./Drawer";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Opener
      </button>
      <button type="button">Outside</button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Detail" footer={<button type="button">Footer action</button>}>
        <input aria-label="First field" />
        <a href="#x">A link</a>
        <button type="button" disabled>
          Disabled
        </button>
        <input aria-label="Last field" />
      </Drawer>
    </>
  );
}

describe("Drawer focus management (L10)", () => {
  it("cycles Tab and Shift+Tab inside the dialog, never reaching the page behind it", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Opener" }));
    const dialog = await screen.findByRole("dialog", { name: "Detail" });
    await waitFor(() => expect(dialog).toHaveFocus());

    const order = ["Close panel", "First field", "A link", "Last field", "Footer action"];
    const seen: string[] = [];
    for (let i = 0; i < order.length; i++) {
      await user.tab();
      const active = document.activeElement as HTMLElement;
      expect(dialog.contains(active)).toBe(true);
      seen.push(active.getAttribute("aria-label") ?? active.textContent ?? "");
    }
    expect(seen).toEqual(order);
    // one more Tab wraps to the first control instead of leaving the dialog
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close panel" }));
    // Shift+Tab from the first wraps to the last
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Footer action" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByLabelText("Last field"));
  });

  it("pulls focus back in when it lands outside the dialog", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Opener" }));
    const dialog = await screen.findByRole("dialog");
    screen.getByRole("button", { name: "Outside" }).focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("closes on Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Opener" });
    await user.click(opener);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });
});
