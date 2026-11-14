import type { ReactNode } from "react";

import { ChatPanel } from "../components/hr-chat/ChatPanel";
import { MyHrQuestions } from "../components/hr-chat/MyHrQuestions";
import { Card, PageHeader } from "../components/ui";

/* Ask HR: the HR policy chatbot for every signed-in person (Req 4.1). */
export function AskHrPage(): ReactNode {
  return (
    <>
      <PageHeader
        title="Ask HR"
        description="Get a quick answer from approved company HR policies, with the policy it came from."
      />
      <Card title="Ask a policy question">
        <ChatPanel />
      </Card>
      <Card title="My questions to HR" description="Questions you sent to HR and their replies.">
        <MyHrQuestions />
      </Card>
    </>
  );
}
