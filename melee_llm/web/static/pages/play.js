// Placeholder for netplay (Mateo vs a bot from his laptop); another track is building it.
import { api, emptyState, h, mount, table } from "../lib.js";

export default async function play(root) {
  const r = await api("/api/netplay");
  mount(root, h("div.pagehead", {}, h("h1", {}, "Play vs bot"),
    h("div.lede", {}, "Netplay against the bots (HAL, Phillip, MIMIC, Faynt, Reyn, coached bots) from your own Slippi Dolphin.")),
    h("div.card", { style: { maxWidth: "820px" } },
      r.sessions.length ? table([{ label: "Session", key: "id" }, { label: "Opponent", key: "bot" }, { label: "Status", key: "status" }], r.sessions)
        : emptyState("Coming soon", r.note || "Sessions will be listed here once melee_llm/netplay exposes them.")));
}
