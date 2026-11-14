import { MessageCircle } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Drawer } from "../ui";
import { ChatPanel } from "./ChatPanel";

/* Floating "Ask HR" button for the employee screen. Opens the HR policy chat in a side
   panel so a question can be asked from anywhere; focus returns to the button on close. */
export function HrChatLauncher(): ReactNode {
  const [open, setOpen] = useState(false);
  const wasOpen = useRef(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (wasOpen.current && !open) buttonRef.current?.focus();
    wasOpen.current = open;
  }, [open]);
  return (
    <>
      <button ref={buttonRef} className="assist-fab" onClick={() => setOpen(true)}
        aria-label="Ask HR a policy question" aria-expanded={open} aria-haspopup="dialog">
        <MessageCircle size={20} aria-hidden="true" />
      </button>
      {open && (
        <Drawer title="Ask HR" subtitle="Answers from approved company HR policy"
          onClose={() => setOpen(false)}>
          <ChatPanel compact />
        </Drawer>
      )}
    </>
  );
}
