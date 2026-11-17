// Brute: what the frame-by-frame search of the game found about perfect play, told for Melee players.
// Every number is from docs/optimal-play.md or from a trace in brute/clips.json (scripts/optimal_play_animations.py).
// The last block reads brute/status.json, so the running search can be reported without touching this file.
import { api, badge, h, link, mount } from "../lib.js";
import { mountPlayer } from "../brute/player.js";

const html = (tag, text) => { const e = h(tag); e.innerHTML = text; return e; };
const p = (text) => html("p", text);
const proven = (text) => h("p.brute-fact", {}, badge("Proven", "hi"), html("span", text));
const sampled = (text) => h("p.brute-fact", {}, badge("Sampled", "muted"), html("span", text));
const tested = (text) => h("p.brute-fact", {}, badge("Tested cases", "muted"), html("span", text));
const verdict = { mate: () => badge("Checkmate", "bad"), guess: () => badge("Must guess", "warn"), safe: () => badge("Safe", "ok"), open: () => badge("Open") };

const DISCARDED = [
  ["Moves that out-range the shine", "Marth's jab reaches 30 units and most characters hit from 12 within 5 frames. Fox sees the move start and answers on the next frame: in 1,085 cases (26 characters, 13 moves) he was never hit first."],
  ["Grabs", "Every grab needs 7 frames or more to come out. None connected, so what a grab leads to never matters."],
  ["Jigglypuff's Rest", "It hits on frame 1 like the shine, but its hitbox is tiny. Standing next to Fox it never connects, and a jump-in Rest is shined before Puff arrives."],
  ["Yoshi's armor", "Yoshi's second jump absorbs the shine at every percent we set. The armor ends when Yoshi attacks, and Fox punished all 7 attacks that would have hit."],
  ["Game & Watch's hammer", "The number is drawn on the frame the button is pressed, so a perfect player can pick the 9 (32%). A jab one frame later interrupts it, and shield blocks it."],
  ["Glitches", "Ness's yo-yo glitch makes his jab hit from 32 to 35 units away on frame 3. Fox still escapes on reaction, and setting it up needs a free hit on Fox first. The other game-deciding glitches need a grab or items."],
  ["Projectiles", "Fox's reflector sends back or stops nearly every timing of every projectile we fired. Only a reflector that came up too late was hit."],
  ["Running the clock", "A timeout goes to the lower percent, but nobody can land the hit that gives a lead. Ledge stalling is capped at 40 to 60 ledge grabs."],
];

const SCORE = [
  ["Both standing, 12.6 or more apart", "safe", "0", "Proven to 8 frames (10 frames at 12.71, mid-stage)."],
  ["Both standing, 11.5 to 12.0 apart", "guess", "0.29", "Proven to 8 frames."],
  ["Both standing, 7.2 to 10.9 apart, room behind blue", "safe", "0", "Proven to 8 frames. Blue's only safe input is to shine first."],
  ["Blue in shield, red free within 14.4", "mate", "1", "Proven to 10 frames, red standing still."],
  ["Red 5 frames into a hop, blue never shields", "mate", "1", "Proven to 10 frames."],
  ["Red 9 frames into a hop, blue never shields", "guess", "0.5", "Proven to 8 frames."],
  ["After the walk in and the flick, 13.19 apart", "guess", "0.25", "Proven to 6 and to 8 frames."],
  ["Red walking in, 13.7 apart", "safe", "0", "Proven to 8 frames. Blue's only safe input is to step away."],
  ["Blue on the ledge, red inside 11.5", "guess", "0.5", "Proven to 8 frames."],
  ["A whole game against a Fox who gives ground", "open", "?", "Sampled only: not broken for good, not shown to hold."],
];

function status(s) {
  const kind = { not_started: ["Not started", "muted"], running: ["Running", "live"], done: ["Finished", "ok"] }[s.state] ?? [s.state, ""];
  return h("div.brute-status", { id: "search-status" },
    h("div.brute-status-head", {}, badge("Search in progress", "warn"), h("b", {}, s.title), badge(...kind)),
    h("p", {}, s.summary),
    s.plan ? h("p.dim", {}, s.plan) : null,
    s.details?.length ? h("dl", {}, s.details.map((d) => [h("dt", {}, d.label), h("dd", {}, d.value)])) : null,
    s.findings?.length ? h("ul", {}, s.findings.map((f) => h("li", {}, f))) : null,
    h("div.small-meta", {}, `Last updated ${s.updated}.`));
}

export default async function brute(root, _params, signal) {
  const [clips, state] = await Promise.all([api("/static/brute/clips.json"), api("/static/brute/status.json")]);
  if (signal.aborted) return;
  document.title = "Brute · Melee × LLM";
  signal.addEventListener("abort", () => { document.title = "Melee × LLM"; });
  const player = (id) => {
    const el = h("div", { "data-scene": id });
    mountPlayer(el, clips.scenes.find((s) => s.id === id), clips, signal);
    return el;
  };
  const step = (n, text) => h("div.brute-step", {}, `${n} · ${text}`);

  mount(root, h("div.brute", {},
    h("header.doc-hero", {},
      h("div.doc-kicker", {}, "Fox vs Fox · Final Destination · searched frame by frame"),
      h("h1", {}, "Is perfect Melee a stalemate?"),
      h("div.doc-meta", {}, h("span", {}, `A brute-force search of the game's own code, in ${clips.scenes.reduce((n, s) => n + s.clips.length, 0)} clips from the simulator`))),
    h("article.prose", {},
      html("p.lede", `At DEF CON 24, Dan Petro <a href="https://www.youtube.com/watch?v=_0Z_oN_CZyA" target="_blank" rel="noopener">argued</a> that Melee played perfectly is a stalemate. Fox's <b>shine</b> (down-B, the reflector) hits on the very first frame, so nothing beats a Fox who reacts, and two perfect Foxes can only stare at each other.`),
      p(`We tested that by brute force. <a href="https://github.com/mateo19182/melee-brute" target="_blank" rel="noopener">melee-brute</a> runs the game's real code, rebuilt from the decompilation, without graphics. It can try an input, look at what happened, and take it back. So we try every input for both players, one frame at a time. A frame is 1/60 of a second.`),
      p(`The short version: the stalemate is real if you stand still at the right distance, but it is <b>not a fortress</b>. An attacker can walk in and make a standing Fox guess. The defender's answer is to back away, and the stage runs out. Whether that wins is still open.`),

      h("h2", {}, "How to read this page"),
      p(`Think of it as chess. A <b>position</b> is one exact situation: where both Foxes are and what they are doing. We sort positions into three kinds.`),
      h("div.brute-kinds", {},
        html("div.k1", `<b>Checkmate</b>The attacker has inputs that land the first hit whatever the defender does, even if the defender sees them coming.`),
        html("div.km", `<b>Must guess</b>Neither side has a sure thing. Both have to pick without knowing what the other picks, like rock-paper-scissors.`),
        html("div.k0", `<b>Safe</b>The defender has inputs that cannot be hit, even if the attacker knows them in advance.`)),
      p(`The <b>value</b> of a position is the attacker's chance of landing a clean first hit (he hits and is not hit) when both play as well as possible. Safe is 0. Checkmate is 1. A guess is in between.`),
      p(`<span class="c1">Red</span> is always the attacker and <span class="c2">blue</span> the defender. Both are Fox, at 0%, on Final Destination. Distances are between the two fighters' centres. A Fox is about 10 units tall and the stage is 171 wide.`),
      p(`Each result carries one of these labels:`),
      proven(`The search tried <b>every</b> sequence of inputs from a fixed list of moves, for a fixed number of frames. It holds for that list and that many frames, and no further.`),
      sampled(`We played some games and report what happened. It rules nothing out.`),
      html("ul.brute-legend", `
        <li><svg width="26" height="22" viewBox="0 0 26 22"><polygon points="13,1 23,6 23,16 13,21 3,16 3,6" fill="currentColor" fill-opacity=".3" stroke="currentColor" stroke-width="2"/></svg>shine, hitbox out (frame 1)</li>
        <li><svg width="26" height="22" viewBox="0 0 26 22"><polygon points="13,1 23,6 23,16 13,21 3,16 3,6" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>shine held, no hitbox</li>
        <li><svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="9" fill="currentColor" fill-opacity=".15" stroke="currentColor" stroke-width="1.5"/></svg>shield</li>
        <li><svg width="14" height="22" viewBox="0 0 14 22"><rect x="2" y="2" width="10" height="18" rx="5" fill="currentColor" fill-opacity=".2" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2.5"/></svg>cannot be hit</li>
        <li><svg width="30" height="22" viewBox="0 0 30 22"><path d="M3 4v9M27 4v9" stroke="currentColor" stroke-width="2"/><path d="M3 8h24" stroke="currentColor" stroke-dasharray="2 3"/></svg>how far red's shine reaches</li>`),
      p(`The drawings are simple shapes placed at the simulator's coordinates, not the game's real hitboxes. The numbers under them are the real ones.`),

      step(1, "how we got here"),
      h("h2", {}, "Why Fox, and why the shine"),
      p(`Before the Fox mirror we tried everything else that might hit a perfect Fox first. None of it works.`),
      h("ul", {}, DISCARDED.map(([what, why]) => html("li", `<b>${what}.</b> ${why}`))),
      tested(`These are sets of cases run in the simulator against a Fox who answers one frame after he sees a move start. They are not exhaustive searches.`),
      p(`One move did get through: Fox's own shine. It was the only move we found that hits on frame 1, before any reaction exists. It reaches 10 to 16 units depending on who it is aimed at, and inside that range it beat every reaction we gave the other character. So the question becomes Fox against Fox.`),

      step(2, "the standoff"),
      h("h2", {}, "Two Foxes, just outside shine range"),
      p(`Against a standing Fox the shine reaches about 10.7 units. Put two Foxes 12.59 apart and neither can do anything. Whatever one starts, the other sees it a frame later and answers. Up close, two shines pressed on the same frame clank and cost nobody anything, and the one who presses a frame earlier wins 5%.`),
      player("standoff"),
      h("div", {}, verdict.safe(), " ", h("b", {}, "Value 0. Both wait.")),
      proven(`8 frames deep at 12.59 apart, blue 12 units from the ledge, with or without shield. Moves allowed for both: stand, dash in or away, shine, jab, short hop, shield, grab, spotdodge, the air and out-of-shield options. Also 8 frames with a longer list (smashes, tilts, walking, crouch, full hop, wavedash), and 10 frames at 12.71 in the middle of the stage.`),
      p(`The shine reaches further against some states than others. A Fox in <b>jumpsquat</b> (the 3 frames of crouch on the ground before any jump) or starting a roll is hit from 12.6. That matters for the next pieces.`),
      player("reach"),

      step(3, "the real rules"),
      h("h2", {}, "Both pick at once, and see each other one frame late"),
      p(`In the real game nobody sees the other's input before choosing. Both press on the same frame, and each learns what the other did one frame later. Some positions are then settled by reacting. In others, reacting is too slow, and both have to commit blind.`),
      p(`For those the search finds the best <b>mix</b>: how often each side should pick each input so that the other cannot gain by changing. The grids below show it. The percentages are the mix, the corner number is the value, and each cell is one outcome you can watch.`),
      p(`The standoff depends on that one-frame reaction. If every input is held for two frames, so answers come up to two frames late, the same 12.59 position without shield is worth 0.382 to the attacker instead of 0.`),
      proven(`0.382 at 8 and at 12 frames, in the corner and mid-stage, defender not shielding.`),

      step(4, "the pieces we have proven"),
      h("h2", {}, "Shield is a one-way door"),
      p(`Holding <b>shield</b> next to a Fox who is free to act feels safe. It is not, because of how you leave it. Acting <b>out of shield</b> means going straight from shield into something else: letting go, jumping, rolling, sidestepping (a spotdodge) or grabbing. Red waits, sees which one blue picked a frame late, and hits it. Every exit loses.`),
      player("door"),
      h("div", {}, verdict.mate(), " ", h("b", {}, "Value 1 within 14.4 units.")),
      proven(`10 frames deep with red standing 7.79, 11.99, 12.59, 13.79 and 14.39 away: all six exits are hit. At 14.99 the value drops to 0.5 and by 16.2 to 0 within 10 frames, though the rolls and the spotdodge are still hit later. At 12.59 it also holds after 2 to 150 frames of shield, mid-stage, facing away, and with red walking or dashing. Not run: red in the middle of an attack or in the air.`),
      p(`The spotdodge lasts 22 frames, longer than the search. Replayed directly, an up smash timed for its end hits for 18%.`),

      h("h2", {}, "A hop, five frames in: forced hit"),
      p(`A Fox in the air beats a Fox on the ground at trading shines. He reaches down further than the other reaches up, and he can cancel his shine with his second jump and shine again. Put red 5 frames into a short hop, 9.42 away and 4.0 up, over a blue who does not shield.`),
      player("hop5"),
      h("div", {}, verdict.mate(), " ", h("b", {}, "Value 1 if blue does not shield.")),
      proven(`10 frames deep. Blue was also given spotdodge, up smash, down smash, crouch, walking and a turn. Red's line then hit 300 of 300 random defenders in the raw simulator. A shield stops it, and then blue is behind the door above.`),

      h("h2", {}, "The same hop, nine frames in: a coin flip"),
      p(`Four frames later red is 7.8 away and 9.2 up. Now blue's shine misses upward if red simply waits, and blue's step away is caught if red shines. Nobody can react. Both flip a coin.`),
      player("coin"),
      h("div", {}, verdict.guess(), " ", h("b", {}, "Value 0.5 if blue does not shield.")),
      proven(`8 frames deep. Giving blue spotdodge, both smashes, crouch and a turn leaves it at 0.5.`),
      p(`With shield allowed the value is 0 inside those 8 frames. But the shield becomes the one-way door once red has landed, and whether blue can get out while red is still landing is not settled. These two hop positions also assume blue stood still while red jumped. In our sample games a hop from 16 or 18 units was jabbed during its jumpsquat. So the hop is a threat, not a proven way in.`),

      step(5, "how the standoff breaks"),
      h("h2", {}, "Walk in, then flick the stick away"),
      p(`This is the line that breaks "stand still and react". It starts from the opening of a match and uses nothing fancy.`),
      player("walk"),
      p(`After 182 frames of walking and one frame of stick away, the Foxes are 13.19 apart and red is in the first frame of a turn. The turn keeps sliding him in. Blue, standing, has <b>no safe input</b>. Here is the guess he faces, with the best mix for both:`),
      player("turn"),
      h("div", {}, verdict.guess(), " ", h("b", {}, "Value 0.25 without shield.")),
      proven(`The line is replayed exactly in the raw simulator. Blue has no safe input at 6 or at 8 frames, and the value is 0.25 at both; 10 frames was not reached. Rules for this search: a shield raised within 15 units of a free Fox is not allowed, because it is the one-way door, and leaving the stage counts as being hit. If blue is allowed to shield anyway the value reads 0, but only by walking through that door. On the way in, with a lookahead of 6 frames, blue never had a hit he could force on red within 3 frames.`),
      p(`Read the grid carefully. A guess is not a win for red. One of blue's guesses hits <i>red</i> first, and we only count red's clean hits. What it shows is that a standing Fox can be forced to gamble, 183 frames into the match, by an attacker who took no risk we could find on the way in.`),
      p(`Standing closer is no better: between 11.5 and 12.0 apart a standing Fox has no safe input either, and the value is 0.29.`),

      h("h2", {}, "So the defender gives ground"),
      p(`Blue does not have to wait for the flick. Against a walking Fox his last safe distance is 13.7, and the only safe input there is to step away.`),
      player("retreat"),
      proven(`At 13.7 against a walking red, stepping away is the only input that holds for 8 frames. Positions already found to be guesses count as lost here. The dash itself is a trace: 21.62 units, ending 3.95 from the ledge.`),

      h("h2", {}, "And the stage runs out"),
      p(`One dash back from his starting spot leaves blue 3.95 units from the ledge. On the ledge itself, with red inside 11.5 units, he has no safe input at all. The reason is the ledge: if red shields blue's shine, the pushback slides blue off the stage.`),
      player("ledge"),
      h("div", {}, verdict.guess(), " ", h("b", {}, "Value 0.5 on the ledge.")),
      proven(`On the ledge blue has no safe input at any distance up to 11.5 (8 frames). The value is 0.5 at 7.3 and at 10.3, and at the 8.52 shown here (our own solve for this clip, 6 and 8 frames). Sliding off the stage counts as a loss under our rules and was not played out. Six units of room behind him are enough to make the position normal again.`),

      h("h2", {}, "What the sample games say"),
      p(`We also built the retreating defender as a player and attacked it: scripted approaches, random inputs, and an attacker that looks one frame ahead for the most dangerous input.`),
      sampled(`114 games from the match start or a placed position, 12,751 frames. The defender was hit first in 5 and hit the attacker first in 73. In 36 nobody was hit. Every clean hit on the defender from the opening came from walking to 13 to 15 units and then doing very little.`),
      sampled(`A defender that remembers every position where it had to guess, and backs out earlier next time, has marked about 500 such positions. Each could be avoided from at most 18 frames earlier. It has not settled: with new attackers, 5 of 21 rounds still found new ones.`),
      sampled(`At the ledge the evidence is thinnest. The defender was not broken there, but those rounds were only 2 to 81 frames long.`),

      step(6, "where it stands"),
      h("h2", {}, "The board so far"),
      h("div.table-wrap.doc-table", {}, h("table.brute-board", {},
        h("thead", {}, h("tr", {}, ["Position", "Kind", "Value", "How we know"].map((t) => h("th", {}, t)))),
        h("tbody", {}, SCORE.map(([pos, kind, value, how]) => h("tr", {}, h("td", {}, pos), h("td", {}, verdict[kind]()), h("td", {}, value), h("td", {}, how)))))),
      p(`So: is perfect Melee a stalemate? <b>Not proven either way.</b> Standing still is not a fortress. No forced win from the opening was found either. It comes down to one question.`),

      h("h2", {}, "Still open: can the attacker take the stage for free?"),
      p(`Each retreat costs blue about 21 units and the stage is finite. If a strong attacker can make him retreat twice without ever walking into a shine or a jab himself, blue ends up guessing on the ledge. Our scripted attackers could not do it, and the one-frame-ahead attacker is too short-sighted to say. A larger search is being set up for exactly this.`),
      status(state),

      h("h2", {}, "Limits"),
      h("ul", {},
        html("li", `Every proof is for a fixed list of moves and 6 to 10 frames. Wavedashes, lasers, tilts and smashes are only in the lists where stated. Crouch cancel and directional influence are in none.`),
        html("li", `Both Foxes are at 0% on Final Destination. No other stage, percent or character was searched this way.`),
        html("li", `"First clean hit" is the whole payoff. Nothing here says what a hit leads to.`)),
      h("p", {}, "Every table, command and number behind this page is in ", link("/docs/optimal-play", "the optimal-play notes"), "."))));
}
