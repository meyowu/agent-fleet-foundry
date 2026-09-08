"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  let token = "", selected = null, cursor = null, controller = null, epoch = 0;
  let catalog = [], before = null, eventMap = new Map(), latestFrame = null, timer = null, historical = false;
  const pretty = (value) => String(value ?? "Not recorded").replaceAll("_", " ");
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }
  function state(text, live = false) {
    $("connection").textContent = text;
    $("connection").dataset.state = live ? "live" : "offline";
  }
  function error(message) { $("error").textContent = message; $("error").hidden = !message; }
  async function request(path, options = {}) {
    const headers = {Authorization: `Bearer ${token}`, ...options.headers};
    const response = await fetch(path, {...options, signal: options.signal ?? AbortSignal.timeout(5000), headers, cache: "no-store", credentials: "omit", redirect: "error"});
    if (response.status === 401) { disconnect(); throw new Error("Access expired. Paste the current terminal token."); }
    if (!response.ok) throw new Error(response.status === 409 ? "Local state could not be verified. Inspect this task in the terminal." : `Request unavailable (${response.status}).`);
    return response;
  }
  function disconnect() {
    epoch++; controller?.abort(); controller = null; clearTimeout(timer); token = "";
    selected = null; cursor = null; eventMap.clear(); latestFrame = null; catalog = []; historical = false;
    $("workspace").hidden = true; $("access").hidden = false; $("disconnect").hidden = true;
    $("token").value = ""; $("runs").replaceChildren(); $("artifact-content").textContent = "";
    $("agents").replaceChildren(); $("events").replaceChildren(); state("Disconnected");
  }
  function renderRuns() {
    const activeRun = document.activeElement?.dataset.runId;
    const buttons = catalog.map((run) => {
      const button = node("button", undefined, "run-item");
      button.setAttribute("aria-current", String(run.run_id === selected));
      button.dataset.runId = run.run_id;
      button.append(node("strong", run.goal), node("span", `${pretty(run.status)} · ${run.run_id.slice(-8)}`));
      button.addEventListener("click", () => select(run.run_id));
      return button;
    });
    $("runs").replaceChildren(...(buttons.length ? buttons : [node("p", "No recorded tasks. Start one from your terminal session.", "hint")]));
    if (activeRun) buttons.find((button) => button.dataset.runId === activeRun)?.focus({preventScroll:true});
    $("older").hidden = !before;
  }
  async function loadCatalog(older = false) {
    const ownEpoch = epoch;
    const data = await (await request(`/api/catalog${older && before ? `?before=${before}` : ""}`)).json();
    if (ownEpoch !== epoch || !token) return;
    if (older) historical = true;
    const seen = new Map((historical ? catalog : []).map((run) => [run.run_id, run]));
    data.runs.forEach((run) => seen.set(run.run_id, run)); catalog = [...seen.values()].sort((a,b) => b.created_at.localeCompare(a.created_at));
    if (older || !historical) before = data.before;
    $("project-name").textContent = data.project.name;
    $("session-count").textContent = `${data.conversations.length} recent sessions · ${data.conversations.filter((x) => x.status !== "idle").length} with a selected turn`;
    renderRuns();
    if (!selected && catalog.length) select(catalog[0].run_id);
  }
  async function refreshLoop() {
    try { await loadCatalog(); } catch (failure) { if (token) error(failure.message); }
    if (token) timer = setTimeout(refreshLoop, 5000);
  }
  function select(runId, replay = false) {
    epoch++; controller?.abort(); selected = runId; cursor = replay && latestFrame ? Object.fromEntries(latestFrame.runs.map((run) => [run.run_id, 0])) : null;
    eventMap.clear(); $("events").replaceChildren(); $("artifact-view").hidden = true;
    $("empty").hidden = true; $("task-detail").hidden = false; renderRuns();
    controller = new AbortController(); stream(epoch, controller.signal);
  }
  function render(frame) {
    latestFrame = frame; cursor = frame.cursors;
    const run = frame.runs[0];
    $("run-id").textContent = run.run_id; $("goal").textContent = run.goal;
    $("run-status").textContent = pretty(run.status);
    $("task-meta").textContent = `${pretty(run.strategy)} · Stage: ${pretty(run.stage)} · Sandbox: ${frame.sandbox} / ${frame.security_level}`;
    const waiting = frame.approvals.length > 0;
    const planning = frame.plan_review?.status;
    $("approval").hidden = !waiting && !["pending", "approved", "consumed"].includes(planning);
    $("approval").textContent = waiting ? `${frame.approvals.length} permission request(s) awaiting review. ${frame.approvals.map((item) => `${item.role}: ${item.action} — ${item.reason}`).join("; ").slice(0, 1200)} Use /approve in the terminal. No browser approvals are available.` : planning === "pending" ? "Execution plan awaits your review. Use /plan approve, /confirm, then /resume in the terminal." : planning === "approved" ? "Plan approved. Use /resume in the terminal to explicitly continue." : "Execution proceeded from an explicitly reviewed plan.";
    $("delivery").textContent = run.verified_complete ? "Verified complete" : frame.evidence ? `Not verified · ${pretty(frame.evidence.effective_verdict)}` : "No verdict yet";
    $("usage").textContent = frame.budget ? `${frame.budget.model_requests} requests · ${frame.budget.reported_total_tokens} reported tokens${frame.budget.completeness !== "complete" ? " · incomplete" : ""}` : "Not recorded";
    $("observed").textContent = new Date(frame.observed_at).toLocaleTimeString();
    $("agent-count").textContent = `${frame.agents.length} recorded instances${frame.truncated_agents ? " · bounded view" : ""}`;
    const agents = [...frame.agents].sort((a,b) => a.started_at.localeCompare(b.started_at) || a.agent_id.localeCompare(b.agent_id)).map((agent) => {
      const card = node("article", undefined, "agent"); const heading = node("div", undefined, "section-heading");
      heading.append(node("h4", agent.role), node("span", pretty(agent.status), "badge"));
      card.append(heading, node("p", `${agent.execution_kind} · iteration ${agent.iteration}`), node("p", `${agent.runtime} · ${agent.provider_model ?? "deterministic offline"}`), node("p", agent.profile ? `Profile: ${agent.profile}` : "Legacy project selection"), node("p", agent.agent_id, "mono")); return card;
    });
    $("agents").replaceChildren(...(agents.length ? agents : [node("p", "No specialist instances have been recorded for this task.", "hint")]));
    $("graph-section").hidden = !frame.graph_nodes.length;
    $("graph").replaceChildren(...frame.graph_nodes.map((item) => node("li", `${item.role} · ${pretty(item.status)} · ${item.depends_on.length ? `after ${item.depends_on.join(", ")}` : "no dependencies"} · scope ${item.scope.join(", ")}`)));
    const evidence = [];
    if (frame.evidence) {
      evidence.push(node("p", `${frame.evidence.changed_paths.length} changed paths · ${frame.evidence.command_results.length} command results`));
      for (const [title, values] of [["Changed paths", frame.evidence.changed_paths], ["Proof gaps", frame.evidence.proof_gaps], ["Remaining risks", frame.evidence.remaining_risks]]) {
        evidence.push(node("h4", title)); const list = node("ul");
        (values.length ? values : ["None recorded"]).forEach((item) => list.append(node("li", typeof item === "string" ? item : `${pretty(item.code)}: ${item.description ?? "Inspect the evidence bundle for details."}${item.required_strength ? ` Required evidence: ${pretty(item.required_strength)}.` : ""}`))); evidence.push(list);
      }
      const commands = node("ul"); frame.evidence.command_results.forEach((item) => commands.append(node("li", `${item.executable} ${item.argv.join(" ")} · exit ${item.exit_code ?? "unknown"} · ${item.strength}${item.timed_out ? " · timed out" : ""}`))); evidence.push(node("h4", "Validation commands"), commands);
    } else evidence.push(node("p", "No delivery evidence yet. A task status alone does not prove completion.", "hint"));
    if (frame.budget) { const details = node("details"), pre = node("pre", JSON.stringify(frame.budget, null, 2)); details.append(node("summary", "Usage and budget breakdown"), pre); evidence.push(details); }
    $("evidence").replaceChildren(...evidence);
    $("artifacts").replaceChildren(...frame.artifacts.map((item) => { const button = node("button", `View ${pretty(item.kind)}`); button.addEventListener("click", () => showArtifact(item.artifact_id)); return button; }));
    if (frame.resync) eventMap.clear();
    frame.events.forEach((event) => eventMap.set(event.event_id, event));
    const events = [...eventMap.values()].sort((a,b) => a.occurred_at.localeCompare(b.occurred_at) || a.run_id.localeCompare(b.run_id) || a.sequence - b.sequence);
    const clipped = events.length > 200; const visible = events.slice(-200); eventMap = new Map(visible.map((event) => [event.event_id,event]));
    $("event-note").textContent = `${frame.resync ? "Cursor reset to verified current history. " : ""}${frame.more_events ? "Catching up. " : ""}${clipped || frame.earlier_events ? "Bounded view; older events omitted. " : ""}Per-run order is authoritative; cross-run times are observational.`;
    const eventRows = new Map([...$("events").children].map((row) => [row.dataset.eventId, row]));
    const eventFocus = $("events").contains(document.activeElement) ? document.activeElement : null;
    $("events").replaceChildren(...visible.map((event) => { if (eventRows.has(event.event_id)) return eventRows.get(event.event_id); const row = node("li"); row.dataset.eventId = event.event_id; row.append(node("time", `${new Date(event.occurred_at).toLocaleTimeString()} · ${event.run_id.slice(-8)} #${event.sequence}`), node("span", pretty(event.event_type))); const details = node("details"); details.append(node("summary", "Details"), node("pre", JSON.stringify(event.payload, null, 2))); row.append(details); return row; }));
    if (eventFocus?.isConnected) eventFocus.focus({preventScroll:true});
  }
  async function stream(ownEpoch, signal) {
    while (!signal.aborted && ownEpoch === epoch && token) {
      const attempt = new AbortController(); let watchdog;
      const resetWatchdog = () => { clearTimeout(watchdog); watchdog = setTimeout(() => attempt.abort(new Error("Observation stalled; last state may be stale.")), 7000); };
      const cancel = () => attempt.abort(); signal.addEventListener("abort", cancel, {once:true}); resetWatchdog();
      try {
        state("Connecting…");
        const response = await request(`/api/runs/${selected}/events`, {signal: attempt.signal, headers: cursor ? {"X-Fleet-Cursors": JSON.stringify(cursor)} : {}});
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
        state("Live · read-only", true); error("");
        try {
          while (true) {
            const {done, value} = await reader.read(); if (done) break;
            resetWatchdog();
            buffer += decoder.decode(value, {stream:true});
            if (buffer.length > 2097152) throw new Error("Observation exceeded its display bound.");
            let separator;
            while ((separator = buffer.indexOf("\n\n")) >= 0) {
              const message = buffer.slice(0, separator); buffer = buffer.slice(separator + 2);
              if (message.startsWith("event: unavailable")) throw new Error("Local state changed or could not be verified. Reconnecting…");
              const line = message.split("\n").find((part) => part.startsWith("data: "));
              if (line && ownEpoch === epoch && !signal.aborted) render(JSON.parse(line.slice(6)));
            }
          }
        } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      } catch (failure) {
        if (signal.aborted || ownEpoch !== epoch || !token) return;
        state("Disconnected · retrying"); error(failure.message);
      } finally { clearTimeout(watchdog); signal.removeEventListener("abort", cancel); }
      if (ownEpoch !== epoch || signal.aborted || !token) return;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  async function showArtifact(artifactId) {
    const ownEpoch = epoch;
    try { const data = await (await request(`/api/runs/${selected}/artifacts/${artifactId}`)).json();
      if (ownEpoch !== epoch) return;
      $("artifact-title").textContent = pretty(data.kind); $("artifact-hash").textContent = `Stored SHA-256: ${data.sha256} · Display is redacted; do not hash this view.`;
      $("artifact-content").textContent = data.content; $("artifact-view").hidden = false; $("artifact-content").focus();
    } catch (failure) { error(failure.message); }
  }
  $("connect-form").addEventListener("submit", async (event) => {
    event.preventDefault(); token = $("token").value; $("token").value = ""; epoch++; error("");
    try { await loadCatalog(); if (!token) return; $("access").hidden = true; $("workspace").hidden = false; $("disconnect").hidden = false; if (!selected) state("Connected · no tasks", true); clearTimeout(timer); timer = setTimeout(refreshLoop, 5000); }
    catch (failure) { disconnect(); error(failure.message); }
  });
  $("disconnect").addEventListener("click", disconnect);
  $("refresh").addEventListener("click", () => loadCatalog().catch((failure) => error(failure.message)));
  $("older").addEventListener("click", () => loadCatalog(true).catch((failure) => error(failure.message)));
  $("replay").addEventListener("click", () => selected && select(selected, true));
  $("close-artifact").addEventListener("click", () => { $("artifact-view").hidden = true; $("artifact-content").textContent = ""; });
  window.addEventListener("pagehide", disconnect);
})();
