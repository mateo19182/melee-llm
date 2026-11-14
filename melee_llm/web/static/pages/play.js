// Placeholder for netplay (Mateo vs a bot from his laptop); another track is building it.
import { api, h, mount, table } from "../lib.js";

export default async function play(root) {
  const r = await api("/api/netplay");
  mount(root, h("div.pagehead", {}, h("h1", {}, "Play vs bot")),
    h("div.card", {}, h("p", {}, "Netplay against the bots (HAL, Phillip, MIMIC, Faynt, Reyn, coached bots) from your own Slippi Dolphin is being built."),
      h("p.dim", {}, "Sessions will be listed here once melee_llm/netplay exposes them."),
      table([{ label: "Session", key: "id" }, { label: "Opponent", key: "bot" }, { label: "Status", key: "status" }], r.sessions,
        { empty: r.note || "No sessions." })));
}
