import { useState, type ReactNode } from "react";

import { PageHeader, Tabs } from "../components/ui";
import { JoiningPanel } from "./JoiningPanel";
import { OffersPanel } from "./OffersPanel";

/* Offers and joining: everything that happens after a candidate is selected. */
export function OnboardingPage(): ReactNode {
  const [tab, setTab] = useState("offers");
  return (
    <>
      <PageHeader
        title="Offers & joining"
        description="After someone is selected: prepare and send the offer, then collect and check joining documents, send joining information and welcome the new joiner."
      />
      <Tabs
        label="Offers and joining"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "offers", label: "Offers" },
          { id: "joining", label: "Joining cases" },
        ]}
      />
      {tab === "offers" ? <OffersPanel onOpenJoining={() => setTab("joining")} /> : <JoiningPanel />}
    </>
  );
}
