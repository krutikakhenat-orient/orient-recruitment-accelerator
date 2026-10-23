import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/* Orient HR Assistance — a built-in, deterministic help assistant.

   It is intentionally rule-based (no LLM dependency), matching the product principle
   that the platform must run without any AI service. It answers common how-to questions
   about the hiring workflow, governance rules, and navigation, and offers quick actions.
   It never gives hiring decisions or legal advice. */

interface Msg {
  role: "bot" | "user";
  text: string;
  chips?: { label: string; to?: string; ask?: string }[];
}

interface Answer {
  keywords: RegExp;
  reply: string;
  chips?: { label: string; to?: string; ask?: string }[];
}

const ANSWERS: Answer[] = [
  {
    keywords: /(create|new).*(campaign|project)|start.*hir/i,
    reply:
      "To start hiring: 1) create a Project (the approved need), 2) create a Campaign under it, " +
      "3) upload & approve a JD, 4) configure & approve rules + thresholds, 5) build & approve the " +
      "application form, 6) approve and publish. Publication is blocked until all of those exist.",
    chips: [
      { label: "Open Projects", to: "/projects" },
      { label: "Open Campaigns", to: "/campaigns" },
    ],
  },
  {
    keywords: /(upload|add).*(jd|job description)|jd/i,
    reply:
      "Open a campaign, go to the Job Description tab, and upload a PDF/DOCX/TXT. The file is scanned " +
      "and a draft is extracted for you to review. Extraction is only a suggestion — review, then " +
      "approve. Approved JD versions are immutable; changes create a new version.",
    chips: [{ label: "Open Campaigns", to: "/campaigns" }],
  },
  {
    keywords: /(rule|threshold|screen)/i,
    reply:
      "Rules are typed criteria with weights and a mandatory flag. A rule set must be approved by " +
      "someone other than its creator (separation of duties). Thresholds need a reason and a distinct " +
      "approver (four-eyes). Screening is deterministic and explainable — every criterion shows its " +
      "evidence and awarded points, and the result is reproducible. It never auto-rejects.",
    chips: [{ label: "Open Campaigns", to: "/campaigns" }],
  },
  {
    keywords: /(review|manual|conflict|low confidence)/i,
    reply:
      "Anything with missing evidence, low confidence, a conflict, or a borderline score is routed to " +
      "the Review Queue for a human. Confirm or correct values there — corrections always keep the " +
      "original extracted value plus your reason.",
    chips: [{ label: "Open Review Queue", to: "/reviews" }],
  },
  {
    keywords: /(interview|slot|invite|assess)/i,
    reply:
      "Interview invitations require an authorised approval (no auto-invite). Assign a capacity-limited " +
      "slot, record attendance, then capture a structured panel assessment. The panel never sees the " +
      "pre-screening internals, and there are no personality/voice/face inference features.",
  },
  {
    keywords: /(candidate|apply|application form|public)/i,
    reply:
      "Candidates apply through a public, campaign-specific link — no account needed. They give privacy " +
      "consent (and optionally opt into the talent pool), upload a resume, and confirm extracted data. " +
      "The form never collects protected attributes like age, gender, religion, or disability.",
  },
  {
    keywords: /(talent pool|rediscover)/i,
    reply:
      "The talent pool only contains candidates who gave a separate, explicit opt-in. A match is " +
      "advisory — a recruiter must verify evidence before contacting anyone. Candidates can withdraw " +
      "consent at any time.",
    chips: [{ label: "Open Talent Pool", to: "/talent-pool" }],
  },
  {
    keywords: /(privacy|retention|delete|gdpr|consent|withdraw)/i,
    reply:
      "Privacy requests (access/export, correction, deletion, restriction, consent withdrawal) have an " +
      "auditable lifecycle. Retention policies are configurable per record category and every retention " +
      "action is logged. Note: the platform provides controls that support compliance — it is not a " +
      "legal determination on its own.",
    chips: [{ label: "Open Privacy & Retention", to: "/privacy" }],
  },
  {
    keywords: /(user|account|sign ?up|register|role|permission)/i,
    reply:
      "Staff accounts are created by a System Administrator (there is no public signup). Each user gets " +
      "least-privilege roles, and permissions only apply to campaigns they're assigned to. Candidates " +
      "don't sign up — they apply to a specific campaign.",
    chips: [{ label: "Open Administration", to: "/admin" }],
  },
  {
    keywords: /(score|explain|evidence|reproduc)/i,
    reply:
      "Every score is reproducible from the stored inputs and the approved rule version. Open an " +
      "application's screening result to see each criterion: the requirement, the candidate evidence, " +
      "its source and confidence, and the awarded vs maximum points with a reason.",
  },
];

const FALLBACK =
  "I can help with the hiring workflow, JDs, rules & screening, the review queue, interviews, " +
  "candidate applications, the talent pool, privacy/retention, and administration. Try a question or a " +
  "quick action below.";

const STARTERS = [
  { label: "How do I create a campaign?", ask: "How do I create a campaign?" },
  { label: "How does screening work?", ask: "How does screening work?" },
  { label: "What is the review queue?", ask: "What is the review queue?" },
  { label: "How do candidates apply?", ask: "How do candidates apply?" },
];

function answerFor(input: string): Msg {
  const match = ANSWERS.find((a) => a.keywords.test(input));
  if (match) return { role: "bot", text: match.reply, ...(match.chips ? { chips: match.chips } : {}) };
  return { role: "bot", text: FALLBACK, chips: STARTERS };
}

export function OrientAssistant(): ReactNode {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "bot",
      text:
        "Hello — I'm Orient HR Assistance. I can guide you through the recruitment workflow and the " +
        "platform's governance rules. What would you like to do?",
      chips: STARTERS,
    },
  ]);
  const bodyRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  const send = (text: string): void => {
    const q = text.trim();
    if (!q) return;
    setMessages((m) => [...m, { role: "user", text: q }, answerFor(q)]);
    setInput("");
  };

  if (!open) {
    return (
      <button className="assist-fab" onClick={() => setOpen(true)} aria-label="Open Orient HR Assistance">
        💬
      </button>
    );
  }

  return (
    <aside className="assist-panel" aria-label="Orient HR Assistance">
      <div className="assist-head">
        <span style={{ fontSize: "1.3rem" }} aria-hidden="true">
          🤝
        </span>
        <div style={{ flex: 1 }}>
          <div className="assist-head__title">Orient HR Assistance</div>
          <div className="assist-head__sub">Guidance • runs without any external AI</div>
        </div>
        <button
          className="btn btn--ghost btn--sm"
          style={{ color: "#fff" }}
          onClick={() => setOpen(false)}
          aria-label="Close assistant"
        >
          ✕
        </button>
      </div>
      <div className="assist-body" ref={bodyRef}>
        {messages.map((m, i) => (
          <div key={i} className={`assist-msg ${m.role === "user" ? "assist-msg--user" : ""}`}>
            <div className={`assist-bubble assist-bubble--${m.role}`}>
              {m.text}
              {m.chips && (
                <div className="assist-chips">
                  {m.chips.map((chip, ci) => (
                    <button
                      key={ci}
                      className="assist-chip"
                      onClick={() => {
                        if (chip.to) {
                          navigate(chip.to);
                          setOpen(false);
                        } else if (chip.ask) {
                          send(chip.ask);
                        }
                      }}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <form
        className="assist-foot"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the workflow…"
          aria-label="Ask Orient HR Assistance"
        />
        <button className="btn btn--primary btn--sm" type="submit">
          Send
        </button>
      </form>
      <span style={{ display: "none" }}>{location.pathname}</span>
    </aside>
  );
}
