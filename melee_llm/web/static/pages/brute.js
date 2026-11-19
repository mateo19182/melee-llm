// Brute: what the frame-by-frame search of the game found about perfect play, told for Melee players.
// The page follows one argument from the start of a match: what holds for the whole game, the road from 120 units
// to contact (brute/road.json, section 15's raw outputs), then one card per situation saying how play gets there
// and who has to allow it, what is proven there and what that does not prove, and a scoreboard.
// Every number is from docs/optimal-play.md or from brute/clips.json and brute/road.json
// (scripts/optimal_play_animations.py). The last block reads brute/status.json.
import { api, badge, h, link, mount } from "../lib.js";
import { mountPlayer } from "../brute/player.js";

const html = (tag, text) => { const e = h(tag); e.innerHTML = text; return e; };
const p = (text) => html("p", text);
const LABELS = { start: ["Proven from the start", "hi"], here: ["Proven in the position", "ok"], sampled: ["Sampled", "muted"],
  assumed: ["Assumed", "muted"], open: ["Open", "warn"] };
const fact = (kind, text) => h("p.brute-fact", {}, badge(...LABELS[kind]), html("span", text));
const verdict = { mate: () => badge("Forced hit", "bad"), guess: () => badge("Must guess", "warn"), safe: () => badge("Safe", "ok") };

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

// The road: the 120 units of the start on the left, contact on the right. The first slice stands for everything
// beyond 25 units, which was not searched; the rest is to scale.
const FAR = 13, AXIS = [25.5, 8];
const at = (gap) => FAR + 1 + (AXIS[0] - gap) / (AXIS[0] - AXIS[1]) * (99 - FAR - 1);
const LANES = [["stand", "Red standing still"], ["walk", "Red walking in"], ["dash", "Red a few frames into a dash in"]];
const INPUT = { wait: "stand still", in: "dash in", out: "dash away", walk_in: "walk in", walk_out: "walk away", shine: "shine", jab: "jab",
  hop: "short hop", shield: "shield", grab: "grab", spotdodge: "spotdodge" };
const PINS = [[14.39, "3", "the door: any distance up to 14.39"], [13.71, "6", "the retreat: 13.71"], [13.19, "2", "the turn: 13.19"],
  [12.59, "1", "the standoff: 12.59"], [10.19, "4·5", "the hop starts here: 10.19"], [8.52, "7", "the ledge: 8.52, with blue on the ledge, where this mid-stage map does not apply"]];

function road(R) {
  const kind = (c) => !c.safe.length ? "bad" : c.safe.includes("wait") ? "ok" : "warn";
  const says = (c) => `${c.gap} apart: ` + (c.safe.length ? "safe inputs: " + c.safe.map((m) => INPUT[m]).join(", ") : "no safe input");
  const pin = ([gap, n, what], k) => h(`span.road-pin.r${k % 3}${n === "7" ? ".off" : ""}`, { style: { left: at(gap) + "%" }, title: what }, n);
  return h("div.road", { id: "road", role: "img", "aria-label": "The distance between the two Foxes from the 120 units of the match start down to contact, with the positions searched mid-stage and where each situation on this page sits." },
    h("div.road-pins", {}, h("span.road-pin.s", { style: { left: FAR / 2 + "%" }, title: "the match start: 120 apart" }, "start"), PINS.map(pin)),
    h("div.road-body", {},
      h("span.road-reach", { style: { left: at(10.7) + "%" } }),
      LANES.map(([key, name]) => h("div.road-lane", {}, h("div.road-name", {}, name),
        h("div.road-track", {}, h("span.road-far", { style: { width: FAR + "%" }, title: "120 to 25 units: not searched" }),
          R.cells.filter((c) => c.kind === key).map((c) => h(`span.road-cell.${kind(c)}`, { style: { left: at(c.gap) + "%" }, title: says(c) })))))),
    h("div.road-axis", {}, h("span", { style: { left: "0%" } }, "120"), [25, 20, 15].map((g) => h("span", { style: { left: at(g) + "%" } }, String(g))),
      h("span.reach", { style: { left: at(10.7) + "%" } }, "10.7")),
    h("div.road-key", {}, [...PINS].sort((x, y) => x[1].localeCompare(y[1])).map(([, n, what]) => h("span", {}, h("span.road-pin", {}, n), what))),
    h("div.road-key", {},
      html("span", `<i class="road-cell ok"></i>standing still is safe`), html("span", `<i class="road-cell warn"></i>standing still is not safe, another input is`),
      html("span", `<i class="road-cell bad"></i>no safe input`), html("span", `<i class="road-far"></i>not searched`),
      html("span", `<i class="road-reach"></i>how far a shine reaches a standing Fox`)));
}

const BANDS = [
  ["far", "120 down to 25", "Not searched", "assumed", `Nothing we measured reaches this far. The longest reach we found one frame before a hit is 21.9 units (a jab), and outside a roll a Fox moves at most 2.4 units a frame. That was measured over 8 frames from 11 starting positions, with no lasers in the list of moves. So nothing is expected to happen out here, but that is an assumption, not a proof.`],
  ["ok", "25 down to 14.7", "Room to wait", "here", `Blue has several safe inputs against all three approaches, and standing still is one of them.`],
  ["warn", "14.1 down to 12.9, red walking in", "Step away", "here", `Standing still is no longer safe. At 14.07 and 13.47 only stepping away is (a dash or a walk away). It costs little: adding the rule "blue loses if he is ever 3 units behind where he started" changed no square on the map. Against a dash in, from 13.55 to 12.35, waiting is not safe either; stepping away or a jab is.`],
  ["ok", "13.3 and 12.7, both standing", "The standoff", "here", `Waiting is safe, and so is stepping away.`],
  ["bad", "12.1 and 11.5, both standing", "No safe input", "here", `Every input blue has can be punished by a red who sees it first. But this position is a mirror image, so red is in the same trouble. Solved with both picking at once at 12.11, the net value (red's clean first hits minus blue's) is exactly 0, and both wait.`],
  ["warn", "10.9 and closer with red standing, 11.7 and closer with red walking", "Shine first", "here", `Blue's only safe input is to shine before red does (measured down to 9.87). A red who is in the middle of a dash at these distances is committed to it, and blue has many safe inputs.`],
];

function status(s) {
  const kind = { not_started: ["Search not started", "muted"], running: ["Search running", "live"], done: ["Search finished", "ok"] }[s.state] ?? [s.state, ""];
  return h("div.brute-status", { id: "search-status" },
    h("div.brute-status-head", {}, badge(...kind), h("b", {}, s.title)),
    h("p", {}, s.summary),
    s.plan ? h("p.dim", {}, s.plan) : null,
    s.details?.length ? h("dl", {}, s.details.map((d) => [h("dt", {}, d.label), h("dd", {}, d.value)])) : null,
    s.findings?.length ? h("ul", {}, s.findings.map((f) => h("li", {}, f))) : null,
    s.next?.length ? [h("h3", {}, "Next steps"), h("ul", {}, s.next.map((f) => h("li", {}, f)))] : null,
    h("div.small-meta", {}, `Last updated ${s.updated}.`));
}

export default async function brute(root, _params, signal) {
  const [clips, state, R] = await Promise.all(["clips", "status", "road"].map((f) => api(`/static/brute/${f}.json`)));
  if (signal.aborted) return;
  const site = document.title;
  document.title = "Brute · Melee × LLM";
  signal.addEventListener("abort", () => { document.title = site; });
  const scene = (id) => clips.scenes.find((s) => s.id === id);
  const player = (id) => {
    const el = h("div", { "data-scene": id });
    mountPlayer(el, scene(id), clips, signal);
    return el;
  };
  const step = (n, text) => h("div.brute-step", {}, `${n} · ${text}`);
  const list = (items) => h("ul", {}, items.map((t) => html("li", t)));
  // How force.corner() staged a position, as measured by the lead-in clip of its scene.
  const F = Object.fromEntries(clips.scenes.filter((s) => s.setup).map((s) => [s.id, s.setup.facts]));
  const staging = (f) => `Frames 1 to ${f.faced} are staging, not play: blue walks ${f.blue_walks.toFixed(1)} units toward the ledge behind him, stops and turns round to face red. That leaves him ${f.room.toFixed(1)} units of stage at his back.`;
  const walkIn = (f) => `Frames ${f.faced + 1} to ${f.released}: red walks in for ${f.released - f.faced} frames. Blue stands still. Red lets go of the stick ${f.let_go} units away and slides to a stop ${f.standing} away.`;
  const net = (kind) => R.net.find((n) => n.attacker === kind);
  const billions = (R.positions / 1e9).toFixed(1);

  // One situation: how play gets there from the start and who has to allow it, what is proven, what is not.
  const card = (n, id, title, where, { how, allow, show, result, proven, not }) => h("section.brute-card", { id },
    h("header", {}, h("span.road-pin", {}, n), h("h2", {}, title), h("span.brute-where", {}, where)),
    h("div.brute-part.how", {}, h("h3", {}, "How play gets here from the start"), how,
      h("p.brute-allow", {}, h("b", {}, "Who has to allow it. "), html("span", allow))),
    show, result ? h("div.brute-result", {}, result) : null,
    h("div.brute-part.is", {}, h("h3", {}, "What is proven here"), proven),
    h("div.brute-part.not", {}, h("h3", {}, "What it does not prove"), list(not)));

  mount(root, h("div.brute", {},
    h("header.doc-hero", {},
      h("div.doc-kicker", {}, "Fox vs Fox · Final Destination · searched frame by frame"),
      h("h1", {}, "Is perfect Melee a stalemate?"),
      h("div.doc-meta", {}, h("span", {}, `A brute-force search of the game's own code, in ${clips.scenes.reduce((k, s) => k + s.clips.length + (s.setup ? 1 : 0), 0)} clips from the simulator`))),
    h("article.prose", {},
      html("p.lede", `At DEF CON 24, Dan Petro <a href="https://www.youtube.com/watch?v=_0Z_oN_CZyA" target="_blank" rel="noopener">argued</a> that Melee played perfectly is a stalemate. Fox's <b>shine</b> (down-B, the reflector) hits on the very first frame, so nothing beats a Fox who reacts, and two perfect Foxes can only stare at each other.`),
      p(`We tested that by brute force. <a href="https://github.com/mateo19182/melee-brute" target="_blank" rel="noopener">melee-brute</a> runs the game's real code, rebuilt from the decompilation, without graphics. It can try an input, look at what happened, and take it back. So we try every input for both players, one frame at a time. A frame is 1/60 of a second.`),
      p(`The short version: from the start of a match neither Fox is favoured, and that is a proof. Everything else is proven for one position at a time, a few frames deep. Those pieces show that standing still is not enough, and that in every situation below where the attacker is ahead, the defender did something he did not have to do. They do not add up to a proof of the stalemate, or against it.`),

      h("h2", {}, "What is certain before any search"),
      p(`A match on Final Destination starts as a mirror image. Both Foxes stand 60 units from the centre, 120 apart, facing each other, with the same character and the same options.`),
      p(`Score the game like this: whoever lands the first clean hit (he hits and is not hit) wins, and what one Fox gains the other loses. That is a <b>zero-sum</b> game. Then with best play neither Fox can be favoured from the start. If one side of the mirror had an edge, the other Fox could play the same plan mirrored and have the same edge, and both cannot be ahead at once. So the value of the whole game is exactly 0.`),
      fact("start", `This is a proof by symmetry. It needs no search, and it has no limit on frames or moves. It assumes the game treats both players the same. Melee breaks a few exact ties by controller port, such as two grabs that connect on the same frame; we ignore that.`),
      p(`So "who wins" is settled, and it was the wrong question. The real questions are these:`),
      html("ol.brute-questions", `
        <li>Is that 0 a <b>standoff</b>, where a Fox can never be made to guess? Or is it a <b>fight</b>, where both have to guess and their chances cancel out?</li>
        <li>Does a Fox exist who can <b>never be hit first</b>: for certain, not just on average?</li>`),
      p(`Neither is answered. The rest of this page is what we know about them, sorted by how we know it: what holds from the start, what holds only once you are in a position, what was only sampled, and what is open.`),

      h("h2", {}, "How to read this page"),
      p(`Think of it as chess. A <b>position</b> is one exact situation: where both Foxes are and what they are doing. <span class="c1">Red</span> is always the attacker and <span class="c2">blue</span> the defender. Both are Fox, at 0%. Distances are between the two fighters' centres. A Fox is about 10 units tall and the stage is 171 wide. We sort positions into three kinds.`),
      h("div.brute-kinds", {},
        html("div.k1", `<b>Forced hit</b>Red has inputs that land the first hit whatever blue does, even if blue sees them coming.`),
        html("div.km", `<b>Must guess</b>Neither side has a sure thing. Both have to pick without knowing what the other picks, like rock-paper-scissors.`),
        html("div.k0", `<b>Safe</b>Blue has inputs that cannot be hit, even if red knows them in advance.`)),
      p(`The search is run in two ways, and each result says which.`),
      html("ul", `
        <li><b>Red sees first.</b> Red is shown each of blue's inputs before he answers. This is harsher on blue than the real game. An input that survives it is a <b>safe input</b>: it cannot be punished even when read.</li>
        <li><b>Both at once.</b> Both press on the same frame, and each learns what the other did one frame later, as in the real game. Where reacting is too slow, the search finds the best <b>mix</b>: how often each side should pick each input so that the other cannot gain by changing. The grids in the clips show it.</li>`),
      p(`The <b>value</b> of a position is red's chance of landing a clean first hit when both play as well as possible. Safe is 0, a forced hit is 1, a guess is in between. Where we say <b>net value</b>, blue's clean first hits are subtracted, so a position that is equally dangerous for both is worth 0.`),
      p(`Every claim carries one of these labels:`),
      fact("start", `True from frame 0 of a match. We say what, if anything, the other Fox has to do for it.`),
      fact("here", `The search tried <b>every</b> sequence of inputs from a fixed list of moves, for a fixed number of frames, starting from one exact position. It holds for that position, that list and that many frames. It says nothing about whether best play ever reaches the position.`),
      fact("sampled", `We played some games and report what happened. It rules nothing out.`),
      fact("assumed", `Reasoning we have not searched.`),
      fact("open", `Not known.`),
      html("ul.brute-legend", `
        <li><svg width="26" height="22" viewBox="0 0 26 22"><polygon points="13,1 23,6 23,16 13,21 3,16 3,6" fill="currentColor" fill-opacity=".3" stroke="currentColor" stroke-width="2"/></svg>shine, hitbox out (frame 1)</li>
        <li><svg width="26" height="22" viewBox="0 0 26 22"><polygon points="13,1 23,6 23,16 13,21 3,16 3,6" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>shine held, no hitbox</li>
        <li><svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="9" fill="currentColor" fill-opacity=".15" stroke="currentColor" stroke-width="1.5"/></svg>shield</li>
        <li><svg width="14" height="22" viewBox="0 0 14 22"><rect x="2" y="2" width="10" height="18" rx="5" fill="currentColor" fill-opacity=".2" stroke="currentColor" stroke-width="1.5" stroke-dasharray="3 2.5"/></svg>cannot be hit</li>
        <li><svg width="30" height="22" viewBox="0 0 30 22"><path d="M3 4v9M27 4v9" stroke="currentColor" stroke-width="2"/><path d="M3 8h24" stroke="currentColor" stroke-dasharray="2 3"/></svg>how far red's shine reaches</li>`),
      p(`In the clips the Foxes are drawn in their real poses at the simulator's coordinates. The poses are not the game's hitboxes. The numbers under them are the real ones.`),

      step(1, "how we got to Fox"),
      h("h2", {}, "Why Fox, and why the shine"),
      p(`Before the Fox mirror we tried everything else that might hit a perfect Fox first. None of it works.`),
      h("ul", {}, DISCARDED.map(([what, why]) => html("li", `<b>${what}.</b> ${why}`))),
      h("p.brute-fact", {}, badge("Tested cases", "muted"), html("span", `These are sets of cases run in the simulator against a Fox who answers one frame after he sees a move start. They are not exhaustive searches.`)),
      p(`One move did get through: Fox's own shine. It was the only move we found that hits on frame 1, before any reaction exists. It reaches 10 to 16 units depending on who it is aimed at, and inside that range it beat every reaction we gave the other character. So the question becomes Fox against Fox.`),

      step(2, "the road from the start"),
      h("h2", {}, "From 120 units to contact"),
      p(`To hit, a Fox has to cross the 120 units between them. This strip is that distance, with the start on the left and contact on the right. Each square is one position we searched in the middle of the stage: red standing still, walking in, or a few frames into a dash, at that distance from a blue who is standing. The colour says whether blue has an input that cannot be punished in the next 8 frames, even by a red who sees each input before he answers. The numbered pins are the situations further down.`),
      road(R),
      fact("here", `${R.cells.length} positions, each searched ${R.frames} frames deep with red seeing first: ${billions} billion positions in all. Moves for both: stand, dash or walk in or away, shine, jab, short hop, shield, grab, spotdodge, and what follows from them. Two earlier results are used as rules instead of being searched again: a shield raised within 14.4 units of a free Fox counts as lost (situation 3), and a spotdodge seen early by a Fox standing within 16.8 units counts as hit.`),
      p(`The squares are placed positions. Blue walks 36 units from his starting spot toward the centre and stops, with ${R.room} units of stage behind him. Red walks in from his own spot. "Standing" means he let go of the stick, slid to a stop and stood for 30 frames. "Walking" is the middle of a step. For "a dash" he stopped about 7 units further out, stood, and then dashed until he was inside the distance.`),
      h("div.road-bands", {}, BANDS.map(([cls, where, name, label, text]) => h("div.road-band", {},
        h("div", {}, h(`i.road-cell.${cls}`), h("b", {}, name), h("span", {}, where)), fact(label, text)))),
      fact("here", `The two net values, both ${net("standing").frames} frames deep with both picking at once and leaving the stage counted as a loss: both standing ${net("standing").gap} apart is worth exactly ${net("standing").value}, and red walking in at ${net("walk_slow").gap} is worth exactly ${net("walk_slow").value}. In both, the best play for each side is to wait.`),
      p(`What the map does not say. It covers ${R.cells.length} exact positions, not every state red can be in: situation 2 below is a position that is not on it (red in the first frame of a turn), and there blue has no safe input. So the map is not a proof that blue can always stay safe. And 8 frames is short: a plan that takes longer to pay off is invisible to it.`),

      step(3, "the situations"),
      h("h2", {}, "Seven situations, and how play gets into each"),
      p(`Each card answers three things. How does play get here from the start of the match, and who has to allow it? What is proven once you are here? And what does that not prove? Five of the seven positions were <b>placed</b>: built by a fixed script, not reached by two players trying to win. In those clips, press <b>From the match start</b> to watch the script run.`),

      card("1", "standoff", "The standoff", "12.59 apart, both standing", {
        how: [p(`This position is placed. ${staging(F.standoff)}`), p(`${walkIn(F.standoff)} That is frame ${F.standoff.frames}.`)],
        allow: `Both. Blue has to let red come this close: he could step away earlier. Red has to choose to stop here: if he keeps walking, you get situation 2.`,
        show: player("standoff"),
        result: [verdict.safe(), " ", h("b", {}, "Value 0. Both wait.")],
        proven: [
          fact("here", `Both at once, 8 frames deep: red's chance of a clean first hit is 0, and the best play for both is to wait. It holds with or without shield for blue. Moves for both: stand, dash in or away, shine, jab, short hop, shield, grab, spotdodge, the air and out-of-shield options.`),
          fact("here", `With a longer list (smashes, tilts, walking, crouch, full hop, wavedash), blue still has a defence that holds for 8 frames with red seeing first. Waiting is one.`),
          fact("here", `In the middle of the stage it is the same: 12.71 apart is worth 0 to 10 frames, and on the road above waiting is safe at 12.71 and at 13.31.`),
          p(`Why 12.6 and not closer: against a standing Fox the shine reaches about 10.7 units. It reaches further against some states. A Fox in <b>jumpsquat</b> (the 3 frames of crouch on the ground before any jump) or starting a roll is hit from 12.6. Up close, two shines pressed on the same frame clank and cost nobody anything, and the one who presses a frame earlier wins 5%. These clips are single lines replayed in the simulator, not searches.`),
          player("reach")],
        not: [
          `Anything past 8 frames (10 in the middle of the stage). A plan slower than that is not covered.`,
          `That red has to stop here. The standoff is safe to stand in for both; it is not a place play is forced into.`,
          `That it survives a slower reaction. If every input is held for two frames, so answers come up to two frames late, the same position without shield is worth 0.382 to red (8 and 12 frames, near the ledge and mid-stage).`],
      }),

      card("2", "turn", "The turn", "13.19 apart, red turning", {
        how: [p(`This one is real play from frame 0, with no staging. Red holds his stick gently toward blue and walks for 182 frames (3 seconds). On frame 183 he flicks the stick away. Blue does nothing the whole time.`), player("walk"),
          p(`Now the Foxes are 13.19 apart and red is in the first frame of a turn. The turn keeps sliding him in.`)],
        allow: `Only blue, by standing still for 183 frames. Red needs nothing else from him, and took no risk we could find: on the way in, looking 6 frames ahead, blue never had a hit he could force within 3 frames. Blue can refuse by stepping away one frame earlier, at 13.71 (situation 6).`,
        show: player("turn"),
        result: [verdict.guess(), " ", h("b", {}, "Value 0.25 without shield.")],
        proven: [
          fact("start", `Against a Fox who stands still: the 183 frames are replayed exactly in the simulator and end in this position, with both at 0%.`),
          fact("here", `From there blue has no safe input at 6 or at 8 frames (red sees first). Both at once, the value is 0.25 at 6 and at 8 frames, and each side plays wait 50%, step away 25%, shine 25%. 10 frames was not reached. Rules for this search: blue may not raise a shield within 15 units of a free Fox, because that is the door of situation 3, and leaving the stage counts as being hit. If blue may shield anyway the value reads 0, but only by walking through that door.`)],
        not: [
          `Anything about best play from the start. It beats one plan, "stand still and react". Blue has another.`,
          `That red is ahead. A guess is not a win: one of blue's guesses hits <i>red</i> first, and 0.25 counts only red's clean hits. We did not compute the net value of this position.`,
          `Anything past 8 frames.`],
      }),

      card("3", "door", "The door: shield is one-way", "blue in shield, red free within 14.4", {
        how: [p(`This position is placed. ${staging(F.door)}`), p(`${walkIn(F.door)} Then blue raises his shield and holds it for 12 frames while red stands there. That is frame ${F.door.frames}.`)],
        allow: `Blue alone. He raises the shield, and red does nothing to make him. Nothing we searched forces a Fox to shield: on the road above, wherever blue has a safe input he has one that is not shield. The temptation is real, though. In the guesses of situations 2 and 5, shield is the input that avoids guessing right now.`,
        show: player("door"),
        result: [verdict.mate(), " ", h("b", {}, "Value 1 within 14.4 units.")],
        proven: [
          p(`Acting <b>out of shield</b> means going straight from shield into something else: letting go, jumping, rolling, sidestepping (a spotdodge) or grabbing. Red waits, sees which one blue picked a frame late, and hits it.`),
          fact("here", `Both at once, 10 frames deep, blue made to leave his shield, red standing 7.79, 11.99, 12.59, 13.79 and 14.39 away: all six exits are hit. At 14.99 the value drops to 0.5 and by 16.2 to 0 within 10 frames, though the rolls and the spotdodge are still hit later. At 12.59 it also holds after 2 to 150 frames of shield, mid-stage, facing away, and with red walking or dashing.`),
          p(`The search makes blue leave. He can hold on instead, but an untouched shield shrinks and breaks by itself after 196 frames (measured). The spotdodge lasts 22 frames, longer than the search; replayed directly, an up smash timed for its end hits for 18%.`)],
        not: [
          `That red can make blue shield. The door only matters to a Fox who walks through it.`,
          `What happens with red in the middle of an attack or in the air: not run.`,
          `Past 14.4 units, the zeros are only for 10 frames.`],
      }),

      card("4", "hop5", "The hop, five frames in", "red 9.42 away and 4.0 up", {
        how: [p(`This position is placed. ${staging(F.hop5)}`), p(`${walkIn(F.hop5)} That is already inside shine range (10.7), and blue has not moved. Red then short-hops toward him: 3 frames of jumpsquat on the ground, then 2 in the air. Blue still has not moved. That is frame ${F.hop5.frames}.`)],
        allow: `Blue, three times over. He lets red walk to ${F.hop5.standing}, a distance at which his only safe input is to shine first (the road above). He does not shine red's jumpsquat, which a shine reaches from as far as 12.6. And he stands still under the hop. In our sample games a Fox who walked to 12.5 or closer was shined, and hops from 16 or 18 units were jabbed during the jumpsquat.`,
        show: player("hop5"),
        result: [verdict.mate(), " ", h("b", {}, "Value 1 if blue does not shield.")],
        proven: [
          p(`A Fox in the air beats a Fox on the ground at trading shines. He reaches down further than the other reaches up, and he can cancel his shine with his second jump and shine again.`),
          fact("here", `10 frames deep, blue not allowed to shield: red has inputs that land the first hit whatever blue does, even if blue sees each one first. Blue was also given spotdodge, up smash, down smash, crouch, walking and a turn. Red's line then hit 300 of 300 random defenders in the raw simulator. A shield stops it, and then blue is behind the door of situation 3.`)],
        not: [
          `That red can get here against a Fox who is trying to stop him. Whether a defender can always stop the hop from outside shine range was not searched: it needs 25 or more frames from a standing start.`,
          `Anything about a blue who shields, beyond the door.`],
      }),

      card("5", "coin", "The same hop, nine frames in", "red 7.76 away and 9.2 up", {
        how: [p(`This position is placed: it is situation 4 with blue standing still for four more frames. ${walkIn(F.coin)} Red short-hops, and on frame ${F.coin.frames} he is 9 frames into the hop.`)],
        allow: `Blue, as in situation 4, and for four frames longer. Each of those frames he had inputs he did not use.`,
        show: player("coin"),
        result: [verdict.guess(), " ", h("b", {}, "Value 0.5 if blue does not shield.")],
        proven: [
          p(`Now blue's shine misses upward if red simply waits, and blue's step away is caught if red shines. Nobody can react. Both flip a coin.`),
          fact("here", `Both at once, 8 frames deep, blue not allowed to shield: value 0.5. Red plays wait or shine, half each; blue plays step away or shine, half each. Giving blue spotdodge, both smashes, crouch and a turn leaves it at 0.5. The net value is also 0.5 (checked at 4 and 5 frames).`),
          fact("here", `With shield allowed the value is 0 inside those 8 frames: blue shields.`)],
        not: [
          `That red can get here, for the same reasons as situation 4.`,
          `That the shield saves blue. It becomes the door once red has landed. Whether blue can get out while red is still landing is not settled.`],
      }),

      card("6", "retreat", "The retreat", "13.71 apart, red walking in", {
        how: [p(`This is real play from frame 0. It is the walk of situation 2 for 182 frames. Then, at 13.71 apart, blue pushes his stick away for two frames and dashes back. Red keeps walking.`)],
        allow: `Nobody. It is blue's own choice, and it is how he refuses situation 2. To the 8 frames searched, red has no punish for it.`,
        show: player("retreat"),
        result: [verdict.safe(), " ", h("b", {}, "Stepping away is safe. Standing still is not.")],
        proven: [
          fact("here", `Against a red walking in from the opening, at 13.7 stepping away is blue's only input that holds for 8 frames with red seeing first. Positions already found to be guesses count as lost here.`),
          fact("here", `The road above says the same in the middle of the stage (14.07 and 13.47), and that the step costs blue less than 3 units within 8 frames. With both picking at once, red walking in at ${net("walk_slow").gap} is worth a net ${net("walk_slow").value}: approaching gains him nothing.`),
          p(`The dash in the clip is one recorded line, not a result. It carries blue 21.62 units and leaves him 3.95 from the ledge.`)],
        not: [
          `That blue has to give up 21 units. That is how far this dash goes; the search only says he is never forced 3 units back within 8 frames.`,
          `That red cannot take the stage with a slower plan. Every step away costs some stage, the stage is finite, and 8 frames cannot see a squeeze that takes longer.`],
      }),

      card("7", "ledge", "The ledge", "blue on the ledge, red 8.52 away", {
        how: [p(`This position is placed, and it is the most staged of all. Frames 1 to ${F.ledge.walked}: blue walks ${F.ledge.blue_walks.toFixed(1)} units from his starting spot to the ledge by himself. He stops on the very edge and turns round. ${walkIn(F.ledge)} That is inside shine range. Frame ${F.ledge.frames}.`)],
        allow: `Blue. Nothing we found puts him on the ledge: in the middle of the stage, to 8 frames, nothing forces him back even 3 units. In the sample games he got near the ledge only by his own long dashes back (0.5 to 0.8 units from it in three games). He also has to let red stand inside shine range.`,
        show: player("ledge"),
        result: [verdict.guess(), " ", h("b", {}, "Value 0.5 on the ledge.")],
        proven: [
          fact("here", `On the ledge blue has no safe input at any distance up to 11.5 (8 frames, red sees first). Both at once, the value is 0.5 at 7.3 and at 10.3, and at the 8.52 shown here (our own solve for this clip, 6 and 8 frames). The reason is the ledge: if red shields blue's shine, the pushback slides blue off the stage. That counts as a loss under our rules and was not played out.`),
          fact("here", `Net values, 8 frames, both at once. Both standing 10.32 apart: +0.27 for red if leaving the stage counts as a loss, 0 if it costs nothing. Red walking in at 13.9: +0.08 if leaving the stage counts as a loss. Both standing 12.72 apart: 0 if it costs nothing; not solved with the loss rule.`),
          p(`Six units of room behind blue are enough to make the position normal again.`)],
        not: [
          `That red can put blue on the ledge. This is the missing link: the ledge is worth a little to red, and we found no way to get blue there.`,
          `That sliding off the stage really loses. What happens after the slide was not played out, and the whole edge depends on it.`],
      }),

      step(4, "the sample games"),
      h("h2", {}, "A defender that gives ground, played from the start"),
      p(`We also built the retreating defender as a player and attacked it from the match start: scripted approaches, random inputs, and an attacker that looks one frame ahead for the most dangerous input. These are whole games, so nothing in them is staged, but they are samples.`),
      fact("sampled", `114 games from the match start or a placed position, 12,751 frames. The defender was hit first in 5 and hit the attacker first in 73. In 36 nobody was hit. Every clean hit on the defender from the opening came from walking to 13 to 15 units and then doing very little.`),
      fact("sampled", `A defender that remembers every position where it had to guess, and backs out earlier next time, has marked about 500 such positions. Each could be avoided from at most 18 frames earlier, and none reached back to the opening. It has not settled: with new attackers, 5 of 21 rounds still found new ones.`),
      fact("sampled", `At the ledge the evidence is thinnest. The defender was not broken there, but those rounds were only 2 to 81 frames long.`),

      step(5, "where it stands"),
      h("h2", {}, "The scoreboard"),
      h("div.brute-score", { id: "scoreboard" },
        h("div.s-start", {}, h("h3", {}, "Proven from the start"), list([
          `Neither Fox is favoured. The value of the whole game is exactly 0, by symmetry.`,
          `A Fox who only stands still can be made to guess. Red walks 182 frames and flicks his stick, and the position is worth 0.25 to him (6 and 8 frames).`])),
        h("div.s-here", {}, h("h3", {}, "Proven once in the position"), list([
          `Standoff at 12.59: value 0, both wait (8 frames; 10 mid-stage).`,
          `Mid-stage map: blue has a safe input in every square searched except both standing 11.5 to 12.1 apart (8 frames).`,
          `Net value 0 with both standing 12.11 apart, and with red walking in at 13.9 (8 frames).`,
          `Against a walking red at 13.7, only stepping away is safe, and it costs under 3 units (8 frames).`,
          `Shield with a free Fox within 14.4: every exit is hit (10 frames).`,
          `Hop, 5 frames in, no shield: forced hit (10 frames).`,
          `Hop, 9 frames in, no shield: 0.5 (8 frames).`,
          `On the ledge, red inside 11.5: no safe input; net +0.27 if falling loses (8 frames).`,
          `Answers two frames late: the standoff is worth 0.382 to red (8 and 12 frames).`])),
        h("div.s-sampled", {}, h("h3", {}, "Sampled"), list([
          `114 games against the retreating defender: hit first in 5, hit the attacker first in 73.`,
          `About 500 guess positions marked, each avoidable at most 18 frames earlier. New ones still turn up.`,
          `Walking to 12.5 or closer was shined. Hops from 16 or 18 were jabbed in the jumpsquat.`,
          `At the ledge: not broken, in rounds of 2 to 81 frames.`])),
        h("div.s-open", {}, h("h3", {}, "Open"), list([
          `Is the 0 a standoff or a fight?`,
          `Does a Fox who can never be hit first exist?`,
          `Anything deeper than 8 frames (10 for a few positions).`,
          `Moves left out of the searches: lasers, full hop, dash dance, wavedash, crouch cancel, directional influence.`,
          `Distances beyond 25 units: assumed quiet, not searched.`,
          `Whether a defender can always stop the hop, and whether he can leave shield while a hopper lands.`,
          `The net value of the turn at 13.19.`]))),

      h("h2", {}, "What we can and cannot say about Petro's stalemate"),
      p(`<b>We can say this.</b>`),
      list([
        `From the start nobody is favoured. That is the only statement here about the whole game, and it is a proof.`,
        `Standing just outside shine range is safe against a Fox who also stands, for the 8 to 10 frames searched.`,
        `Standing still as a whole plan is not enough. From the start, 183 frames of walking and one flick put a waiting Fox in a guess.`,
        `In every situation on this page where red is ahead, blue did something he did not have to do: he stood still under a hop, shielded, or walked to the ledge.`,
        `In the middle of the stage, 8 frames deep, walking in gains red nothing, and the step away that keeps blue safe costs him under 3 units.`]),
      p(`<b>We cannot say this.</b>`),
      list([
        `That perfect Melee is a stalemate in Petro's sense, where nobody can ever be made to guess. That needs a defence that is safe at every moment of a whole game. What we have is safe inputs for single positions, 8 frames at a time, and sample games in which the best defender we built was still being caught by new lines.`,
        `That it is not one. We found no line from the start that forces a hit. Lines that made our retreating defender guess were found, and each could have been avoided by acting at most 18 frames earlier. Whether that always works is open.`,
        `Anything about plans slower than 8 frames, the moves we left out, other stages, other percents or other characters.`]),

      h("h2", {}, "The latest search"),
      p(`The last search asked whether red can push a retreating blue to the ledge. Its results are in the road and in situations 6 and 7 above. This block is its summary and what comes next.`),
      status(state),

      h("h2", {}, "Limits"),
      h("ul", {},
        html("li", `Every proof is for a fixed list of moves and 6 to 10 frames. Wavedashes, tilts and smashes are only in the lists where stated. Lasers, crouch cancel and directional influence are in none.`),
        html("li", `Both Foxes are at 0% on Final Destination. No other stage, percent or character was searched this way.`),
        html("li", `"First clean hit" is the whole payoff. Nothing here says what a hit leads to.`)),
      h("p", {}, "Every table, command and number behind this page is in ", link("/docs/optimal-play", "the optimal-play notes"), "."))));
}
