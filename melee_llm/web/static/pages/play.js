// Play a bot yourself: locally with play.py for now; netplay from this page comes later (melee_llm/netplay).
import { emptyState, h, link, mount } from "../lib.js";

const CMDS = `cd melee-llm
ISO="$HOME/Downloads/Super Smash Bros. Melee (v1.02 NTSC).iso"

# Our own bot: behaviour-cloned Yoshi
uv run play.py --iso "$ISO" --bot meleebot:bc-6m-v1 --bot-char YOSHI

# Phillip (slippi-ai), the strong one
uv run play.py --iso "$ISO" --bot phillip:gm --bot-char FOX`;

export default async function play(root) {
  mount(root, h("div.pagehead", {}, h("h1", {}, "Play vs bot"),
    h("div.lede", {}, "Play our bots yourself, with a controller, from your own machine.")),
    h("div.card", { style: { maxWidth: "820px" } },
      h("h2", {}, "Locally, from the repo"),
      h("p", {}, "Run this in a clone of the repo. Dolphin opens with you on port 1 and the bot on port 2: pick your character and press Start."),
      h("pre.prompt-box", {}, CMDS),
      h("p", {}, "Stop with Ctrl-C or by closing the Dolphin window. Other bots, controller setup and fixes: ",
        link("/docs/local-play", "docs/local-play"), ".")),
    h("div.card", { style: { maxWidth: "820px", marginTop: "14px" } },
      emptyState("Netplay: coming soon", "Start a session here and play the bots on the server from your own Slippi Dolphin.")));
}
