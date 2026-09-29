import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8200";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || "Vigil request failed");
  }
  return response.status === 204 ? null : response.json();
}

function today() {
  return new Date().toLocaleDateString("en-CA");
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(seconds = 0) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatActiveDuration(totalSeconds) {
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours > 0) {
    return `${hours}h ${mins}m`;
  }
  return `${mins}m`;
}

function formatHoursMins(totalSeconds = 0) {
  const minutes = Math.floor(totalSeconds / 60);
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) {
    return `${mins}m`;
  }
  return `${hours}h ${mins}m`;
}

function formatHeatmapTooltip(focusSeconds = 0, laptopSeconds = 0) {
  if (!focusSeconds && !laptopSeconds) return "0m Focus / 0m Total (0%)";
  const focusStr = formatHoursMins(focusSeconds);
  const laptopStr = formatHoursMins(laptopSeconds);
  const pct = laptopSeconds > 0 ? Math.round((focusSeconds / laptopSeconds) * 100) : 0;
  return `${focusStr} Focus (${pct}%) / ${laptopStr} Total`;
}


function MonthlyGoalBanner({ goals = [], goal = "" }) {
  const list = Array.isArray(goals) && goals.length > 0
    ? goals
    : (goal ? [goal] : []);

  if (!list.length) return null;

  return (
    <div className="monthly-goal-banner">
      <p className="eyebrow">{list.length > 1 ? "MONTHLY FOCUS GOALS" : "MONTHLY FOCUS GOAL"}</p>
      {list.length === 1 ? (
        <p className="goal-text">“{list[0]}”</p>
      ) : (
        <ul className="goals-list">
          {list.map((item, index) => (
            <li key={index} className="goal-item">
              <span className="goal-bullet">🎯</span>
              <span className="goal-text">“{item}”</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DailyValues({ values = [] }) {
  return (
    <section className="card daily-values-card" style={{ marginBottom: 0 }}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">INTENTIONS & GROUND RULES</p>
          <h2>Daily rules</h2>
        </div>
        <span>{values.length} core principles</span>
      </div>
      <div className="values-container">
        <ul className="values-list">
          {values.map((item, index) => (
            <li key={index} className="value-item">
              <span className="value-bullet">•</span>
              <span className="value-text">{item}</span>
            </li>
          ))}
          {!values.length && <li className="empty">No core values set.</li>}
        </ul>
      </div>
    </section>
  );
}

const LOAD_LABELS = {
  well_below: "Well below",
  below: "Below",
  steady: "Steady",
  above: "Above",
  well_above: "Well above",
};

const LOAD_COPY = {
  well_below: "Your recent focus is well below your baseline. A lighter stretch is fine — ease back in when you're ready.",
  below: "Focus is a little under your usual pace lately.",
  steady: "You're in your groove — recent focus matches your baseline.",
  above: "You're pushing above your baseline. Sustainable if you protect your recovery.",
  well_above: "Load is well above your baseline. Watch for burnout and consider a lighter day.",
};

const TREND_COPY = {
  rising: "Load rising vs. a week ago",
  falling: "Load easing vs. a week ago",
  stable: "Holding steady vs. a week ago",
};

function formatMinutes(minutes = 0) {
  const total = Math.round(minutes);
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours === 0) return `${mins}m`;
  return `${hours}h ${mins}m`;
}

function formatDelta(delta) {
  if (delta === null || delta === undefined) return "—";
  const rounded = Math.round(delta);
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function formatDayLabel(dateStr, isToday) {
  if (isToday) return "Today · as of now";
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

// Contiguous runs of points that satisfy `keep`, as SVG path strings.
function linePaths(points, keep) {
  const paths = [];
  let run = [];
  points.forEach((point) => {
    if (point && keep(point)) {
      run.push(point);
    } else if (run.length) {
      paths.push(run);
      run = [];
    }
  });
  if (run.length) paths.push(run);
  return paths.map((points) => points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "));
}

const CHART = { width: 640, height: 220, left: 38, right: 12, top: 12, bottom: 26 };

function FocusLoadChart({ history, hoverIndex, onHover }) {
  const innerWidth = CHART.width - CHART.left - CHART.right;
  const innerHeight = CHART.height - CHART.top - CHART.bottom;
  const count = history.length;
  const step = count > 1 ? innerWidth / (count - 1) : innerWidth;

  const rawMax = Math.max(
    10,
    ...history.map((d) => Math.max(d.flu, d.acuteLoad ?? 0, (d.chronicLoad ?? 0) * 1.1))
  );
  const tick = rawMax > 200 ? 100 : rawMax > 80 ? 50 : rawMax > 40 ? 20 : 10;
  const yMax = Math.ceil(rawMax / tick) * tick;
  const xAt = (index) => CHART.left + (count > 1 ? index * step : innerWidth / 2);
  const yAt = (value) => CHART.top + innerHeight - (value / yMax) * innerHeight;

  const acute = history.map((d, i) => (d.acuteLoad === null ? null : { x: xAt(i), y: yAt(d.acuteLoad) }));
  const chronic = history.map((d, i) =>
    d.chronicLoad === null ? null : { x: xAt(i), y: yAt(d.chronicLoad), partial: d.chronicPartial }
  );

  const bandPoints = history
    .map((d, i) => (d.chronicLoad === null ? null : { x: xAt(i), hi: yAt(d.chronicLoad * 1.1), lo: yAt(d.chronicLoad * 0.95) }))
    .filter(Boolean);
  const bandPath = bandPoints.length > 1
    ? `M${bandPoints.map((p) => `${p.x.toFixed(1)},${p.hi.toFixed(1)}`).join(" L")} L${[...bandPoints]
        .reverse()
        .map((p) => `${p.x.toFixed(1)},${p.lo.toFixed(1)}`)
        .join(" L")} Z`
    : "";

  const ticks = [];
  for (let v = 0; v <= yMax; v += tick) ticks.push(v);

  function indexFromEvent(event) {
    const point = event.touches ? event.touches[0] : event;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((point.clientX - rect.left) / rect.width) * CHART.width;
    const index = Math.round((x - CHART.left) / step);
    return Math.min(count - 1, Math.max(0, index));
  }

  const hovered = hoverIndex !== null ? history[hoverIndex] : null;
  const labelIndexes = new Set(
    count > 1 ? [0, 1, 2, 3, 4].map((j) => Math.round((j * (count - 1)) / 4)) : [0]
  );

  return (
    <svg
      className="focus-chart"
      viewBox={`0 0 ${CHART.width} ${CHART.height}`}
      role="img"
      aria-label={`Focus load over the last ${count} days: daily load with 7-day and 28-day averages`}
      onMouseMove={(event) => onHover(indexFromEvent(event))}
      onTouchStart={(event) => onHover(indexFromEvent(event))}
      onTouchMove={(event) => onHover(indexFromEvent(event))}
      onMouseLeave={() => onHover(null)}
    >
      {ticks.map((value) => (
        <g key={value}>
          <line className="chart-grid" x1={CHART.left} x2={CHART.width - CHART.right} y1={yAt(value)} y2={yAt(value)} />
          <text className="chart-axis" x={CHART.left - 6} y={yAt(value) + 3} textAnchor="end">{value}</text>
        </g>
      ))}
      {bandPath && <path className="chart-band" d={bandPath} />}
      {history.map((d, i) => (
        <rect
          key={d.date}
          className="chart-bar"
          x={xAt(i) - Math.min(step * 0.3, 8)}
          width={Math.min(step * 0.6, 16)}
          y={yAt(d.flu)}
          height={Math.max(0, CHART.top + innerHeight - yAt(d.flu))}
          rx="2"
        />
      ))}
      {linePaths(chronic, () => true).map((d, i) => <path key={`cd${i}`} className="chart-line chronic partial" d={d} />)}
      {linePaths(chronic, (p) => !p.partial).map((d, i) => <path key={`cs${i}`} className="chart-line chronic" d={d} />)}
      {linePaths(acute, () => true).map((d, i) => <path key={`a${i}`} className="chart-line acute" d={d} />)}
      {history.map((d, i) =>
        labelIndexes.has(i) ? (
          <text key={`x${d.date}`} className="chart-axis" x={xAt(i)} y={CHART.height - 8} textAnchor={i === 0 ? "start" : i === count - 1 ? "end" : "middle"}>
            {new Date(`${d.date}T00:00:00`).toLocaleDateString([], { month: "short", day: "numeric" })}
          </text>
        ) : null
      )}
      {hovered && (
        <g pointerEvents="none">
          <line className="chart-rule" x1={xAt(hoverIndex)} x2={xAt(hoverIndex)} y1={CHART.top} y2={CHART.top + innerHeight} />
          {hovered.chronicLoad !== null && <circle className="chart-dot chronic" cx={xAt(hoverIndex)} cy={yAt(hovered.chronicLoad)} r="4" />}
          {hovered.acuteLoad !== null && <circle className="chart-dot acute" cx={xAt(hoverIndex)} cy={yAt(hovered.acuteLoad)} r="4.5" />}
        </g>
      )}
    </svg>
  );
}

const LOAD_RANGES = [30, 60, 90];

function RangeToggle({ value, onChange }) {
  return (
    <div className="range-toggle" role="group" aria-label="Chart range">
      {LOAD_RANGES.map((days) => (
        <button
          key={days}
          type="button"
          className={value === days ? "active" : ""}
          aria-pressed={value === days}
          onClick={() => onChange(days)}
        >
          {days}D
        </button>
      ))}
    </div>
  );
}

function FocusLoadCard({ data, range, onRangeChange }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  useEffect(() => setHoverIndex(null), [range]);
  if (!data) return null;

  const { state, classification, deltaPercent, trend, history = [] } = data;
  const isInsufficient = state === "insufficient_data";
  const shown = hoverIndex !== null ? history[hoverIndex] : history[history.length - 1];
  const shownIsToday = hoverIndex === null || hoverIndex === history.length - 1;
  const pin = deltaPercent === null ? 50 : ((Math.max(-40, Math.min(40, deltaPercent)) + 40) / 80) * 100;
  const baseline = data.chronicFocusMinutesPerDay || 0;
  const todayVsBaseline = baseline > 0 ? Math.min(150, (data.today.focusMinutes / baseline) * 100) : 0;

  return (
    <section className="card focus-load-card">
      <div className="section-heading">
        <p className="eyebrow">FOCUS LOAD · 7 DAY VS 28 DAY</p>
        {classification && <span className={`load-badge ${classification}`}>{LOAD_LABELS[classification]} · {formatDelta(deltaPercent)}</span>}
      </div>

      {isInsufficient ? (
        <p className="load-copy">
          Tracking initial baseline (Day {Math.min(data.daysTracked, 7)} of 7). Focus load unlocks once a full week of activity is recorded.
        </p>
      ) : (
        <>
          <p className="load-copy">
            {LOAD_COPY[classification]} {trend && <strong className={`trend ${trend}`}>{TREND_COPY[trend]}.</strong>}
          </p>
          {state === "preliminary" && (
            <p className="load-note">Preliminary baseline — calibrating (Day {data.daysTracked} of 28). Your baseline sharpens as history builds.</p>
          )}

          <div className="load-gauge" aria-label="Load versus baseline">
            <div className="gauge-track">
              <div className="gauge-band" />
              <div className={`gauge-pin ${classification}`} style={{ left: `${pin}%` }} />
            </div>
            <div className="gauge-scale"><span>−40%</span><span>Baseline</span><span>+40%</span></div>
          </div>

          <div className="load-metrics">
            <div>
              <p className="eyebrow">Acute · 7 days</p>
              <strong>{formatMinutes(data.acuteFocusMinutesPerDay)}/day</strong>
            </div>
            <div>
              <p className="eyebrow">Baseline · 28 days</p>
              <strong>{formatMinutes(data.chronicFocusMinutesPerDay)}/day</strong>
            </div>
            <div>
              <p className="eyebrow">Density today</p>
              <strong>{Math.round(data.densityScore * 100)}%</strong>
              <span className="metric-sub">7-day avg {Math.round(data.acuteDensity * 100)}%</span>
            </div>
            <div>
              <p className="eyebrow">Today vs baseline</p>
              <strong>{formatMinutes(data.today.focusMinutes)}</strong>
              <div className="today-progress"><div style={{ width: `${(todayVsBaseline / 150) * 100}%` }} /></div>
            </div>
          </div>
        </>
      )}

      {history.length > 0 && !isInsufficient && shown && (
        <div className="load-chart">
          <div className="load-chart-header">
            <RangeToggle value={range} onChange={onRangeChange} />
            {data.daysTracked < range && (
              <span className="range-note">Showing all {history.length} days tracked so far</span>
            )}
          </div>
          <div className="load-readout">
            <div>
              <p className="eyebrow">{formatDayLabel(shown.date, shownIsToday)}</p>
              <strong className="readout-load">{shown.flu} <small>load</small></strong>
            </div>
            <div>
              <p className="eyebrow">Load vs baseline</p>
              <strong className={shown.classification ? `readout-delta ${shown.classification}` : "readout-delta"}>
                {formatDelta(shown.deltaPercent)}{shown.classification ? ` · ${LOAD_LABELS[shown.classification]}` : ""}
              </strong>
            </div>
            <div>
              <p className="eyebrow">Focus / laptop</p>
              <strong>{formatMinutes(shown.focusMinutes)} / {formatMinutes(shown.laptopMinutes)}</strong>
              <span className="metric-sub">{Math.round(shown.density * 100)}% density</span>
            </div>
          </div>
          <FocusLoadChart history={history} hoverIndex={hoverIndex} onHover={setHoverIndex} />
          <div className="chart-legend">
            <span><i className="swatch bar" /> Daily load</span>
            <span><i className="swatch acute" /> 7-day average</span>
            <span><i className="swatch chronic" /> 28-day average</span>
            <span><i className="swatch band" /> Steady range</span>
          </div>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [selectedDate, setSelectedDate] = useState(today());
  const [tasks, setTasks] = useState([]);
  const [activeTimeBreakdown, setActiveTimeBreakdown] = useState({ totalSeconds: 0, apps: [] });
  const [summary, setSummary] = useState([]);
  const [focusLoad, setFocusLoad] = useState(null);
  const [focusRange, setFocusRange] = useState(30);
  const [timer, setTimer] = useState({ status: "idle", phase: "work", remaining_seconds: 0 });
  const [userSettings, setUserSettings] = useState({
    pomodoro_duration_minutes: 25,
    sleep_time: "23:00",
    reflection_email: "",
    monthly_goal: "",
    monthly_goals: [],
    core_values: [],
  });
  const [title, setTitle] = useState("");
  const [estimate, setEstimate] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // Settings modal states
  const [showSettings, setShowSettings] = useState(false);
  const [settingsForm, setSettingsForm] = useState({
    pomodoro_duration_minutes: 25,
    sleep_time: "23:00",
    reflection_email: "",
    monthly_goals_text: "",
    core_values_text: "",
  });
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSuccess, setSettingsSuccess] = useState("");
  const [settingsError, setSettingsError] = useState("");

  async function refresh(date = selectedDate) {
    setLoading(true);
    setError("");
    try {
      const [nextTasks, nextSummaryBreakdown, nextSummary, nextTimer, nextSettings, nextFocusLoad] = await Promise.all([
        request("/tasks"),
        request(`/active-time-summary?date=${encodeURIComponent(date)}`),
        request("/activity/summary?days=28"),
        request("/pomodoro"),
        request("/settings"),
        // Optional widget: a failure here must not break the rest of the dashboard.
        request(`/focus-load?days=${focusRange}`).catch(() => null),
      ]);
      setTasks(nextTasks);
      setActiveTimeBreakdown(nextSummaryBreakdown);
      setSummary(nextSummary.days);
      setFocusLoad(nextFocusLoad);
      setTimer(nextTimer);
      if (nextSettings) {
        setUserSettings(nextSettings);
        const goalsText = (nextSettings.monthly_goals && nextSettings.monthly_goals.length > 0)
          ? nextSettings.monthly_goals.join("\n")
          : (nextSettings.monthly_goal || "");
        setSettingsForm({
          pomodoro_duration_minutes: nextSettings.pomodoro_duration_minutes || 25,
          sleep_time: nextSettings.sleep_time || "23:00",
          reflection_email: nextSettings.reflection_email || "",
          monthly_goals_text: goalsText,
          core_values_text: (nextSettings.core_values || []).join("\n"),
        });
      }
    } catch (nextError) {
      setError(nextError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (timer.status !== "running" || !timer.started_at) {
      return;
    }

    const intervalId = setInterval(() => {
      const elapsed = Math.floor((Date.now() - new Date(timer.started_at)) / 1000);
      const nextRemaining = Math.max(0, timer.duration_at_start - elapsed);
      setTimer((prev) => {
        if (prev.remaining_seconds === nextRemaining) return prev;
        return { ...prev, remaining_seconds: nextRemaining };
      });
      if (nextRemaining <= 0) {
        clearInterval(intervalId);
        refresh();
      }
    }, 1000);

    return () => clearInterval(intervalId);
  }, [timer.status, timer.started_at, timer.duration_at_start]);

  async function changeFocusRange(days) {
    setFocusRange(days);
    // Keep the current chart on screen while the new window loads; ignore failures.
    const next = await request(`/focus-load?days=${days}`).catch(() => null);
    if (next) setFocusLoad(next);
  }

  async function saveSettings(e) {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      const monthlyGoalsArray = settingsForm.monthly_goals_text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      const coreValuesArray = settingsForm.core_values_text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

      const updated = await request("/settings", {
        method: "PUT",
        body: JSON.stringify({
          pomodoro_duration_minutes: Number(settingsForm.pomodoro_duration_minutes),
          sleep_time: settingsForm.sleep_time,
          reflection_email: settingsForm.reflection_email.trim() || null,
          monthly_goals: monthlyGoalsArray,
          core_values: coreValuesArray,
        }),
      });
      setUserSettings(updated);
      setSettingsForm((prev) => ({
        ...prev,
        monthly_goals_text: (updated.monthly_goals || []).join("\n"),
        core_values_text: (updated.core_values || []).join("\n"),
      }));
      setSettingsSuccess("Settings saved successfully!");
      setTimeout(() => setSettingsSuccess(""), 3000);
    } catch (err) {
      setSettingsError(err.message);
    } finally {
      setSavingSettings(false);
    }
  }

  async function addTask(event) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      await request("/tasks", {
        method: "POST",
        body: JSON.stringify({ title, estimate_pomodoros: Number(estimate) }),
      });
      setTitle("");
      setEstimate(1);
      refresh();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function updateTask(task, update) {
    try {
      await request(`/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify(update) });
      refresh();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function deleteTask(task) {
    try {
      await request(`/tasks/${task.id}`, { method: "DELETE" });
      refresh();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function startTask(task) {
    try {
      const defaultDuration = (userSettings.pomodoro_duration_minutes || 25) * 60;
      await request("/pomodoro/start", {
        method: "POST",
        body: JSON.stringify({ task_id: task.id, duration_seconds: defaultDuration }),
      });
      refresh();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function timerAction(path, payload) {
    try {
      await request(path, { method: "POST", ...(payload ? { body: JSON.stringify(payload) } : {}) });
      refresh();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  const maxEvents = Math.max(1, ...summary.map((day) => day.event_count));
  const todayStr = today();
  const todayData = summary.find((day) => day.date === todayStr) || { total_laptop_time_seconds: 0 };
  const todayLaptopTime = todayData.total_laptop_time_seconds || 0;
  const focusDurationSeconds = (userSettings.pomodoro_duration_minutes || 25) * 60;

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">LOCAL ACTIVITY & FOCUS</p>
          <h1>Satan</h1>
        </div>
        <div style={{ display: "flex", gap: "0.55rem", alignItems: "center" }}>
          <button className="icon-btn" onClick={() => setShowSettings(true)} title="Settings" aria-label="Settings">
            ⚙️
          </button>
          <button className="secondary" onClick={() => refresh()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <div className="top-row">
        <section className="timer card" style={{ flex: 1.6, marginBottom: 0 }}>
          <div>
            <p className="eyebrow">{timer.phase} session · {timer.status}{timer.pause_reason === "system_sleep" ? " (screen off)" : ""}</p>
            <p className="clock">{formatDuration(timer.remaining_seconds)}</p>
          </div>
          <div className="actions">
            {timer.status === "idle" && (
              <button onClick={() => timerAction("/pomodoro/start", { duration_seconds: focusDurationSeconds })}>
                Start focus ({userSettings.pomodoro_duration_minutes || 25}m)
              </button>
            )}
            {timer.status === "running" && <button className="secondary" onClick={() => timerAction("/pomodoro/pause")}>Pause</button>}
            {timer.status === "paused" && <button onClick={() => timerAction("/pomodoro/resume")}>Resume</button>}
            {timer.status !== "idle" && <button className="danger" onClick={() => timerAction("/pomodoro/stop")}>Stop</button>}
          </div>
        </section>

        <section className="card" style={{ flex: 1, marginBottom: 0, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div>
            <p className="eyebrow">Laptop time today</p>
            <p className="clock" style={{ color: "#80ffd4" }}>{formatActiveDuration(todayLaptopTime)}</p>
          </div>
        </section>
      </div>

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">POMODORO TASKS</p>
            <h2>Focus queue</h2>
          </div>
        </div>
        <form className="task-form" onSubmit={addTask}>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="What needs focus?" maxLength="200" />
          <input type="number" min="1" max="99" value={estimate} onChange={(event) => setEstimate(event.target.value)} aria-label="Estimated Pomodoros" />
          <button>Add</button>
        </form>
        <ul className="tasks">
          {tasks.map((task) => (
            <li key={task.id}>
              <button
                className={`check ${task.status === "done" ? "checked" : ""}`}
                aria-label={`Mark ${task.title} ${task.status === "done" ? "todo" : "done"}`}
                onClick={() => updateTask(task, { status: task.status === "done" ? "todo" : "done" })}
              >
                {task.status === "done" ? "✓" : ""}
              </button>
              <div className="task-copy">
                <strong className={task.status === "done" ? "complete" : ""}>{task.title}</strong>
                <span>{task.completed_pomodoros}/{task.estimate_pomodoros} sessions</span>
              </div>
              <button className="icon" title="Start this task" onClick={() => startTask(task)}>▶</button>
              <button className="icon" title="Delete task" onClick={() => deleteTask(task)}>×</button>
            </li>
          ))}
          {!tasks.length && <li className="empty">Add a task to begin a focused session.</li>}
        </ul>
      </section>

      <MonthlyGoalBanner goals={userSettings.monthly_goals} goal={userSettings.monthly_goal} />

      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">LAST 28 DAYS</p>
            <h2>Activity signal</h2>
          </div>
          <span>{summary.reduce((total, day) => total + day.event_count, 0)} captured events</span>
        </div>
        <div className="contribution-grid" aria-label="28-day activity graph">
          {summary.map((day) => (
            <div
              className="contribution"
              key={day.date}
              title={formatHeatmapTooltip(day.total_focus_time_seconds, day.total_laptop_time_seconds)}
              style={{ opacity: day.event_count ? 0.25 + (day.event_count / maxEvents) * 0.75 : 0.08 }}
            >
              <span className="tooltip-text">
                {formatHeatmapTooltip(day.total_focus_time_seconds, day.total_laptop_time_seconds)}
              </span>
            </div>
          ))}
        </div>
      </section>

      <FocusLoadCard data={focusLoad} range={focusRange} onRangeChange={changeFocusRange} />

      <div className="columns">
        <div className="left-column">
          <DailyValues values={userSettings.core_values} />
        </div>

        <section className="card" style={{ flex: 1, minWidth: 0, marginBottom: 0 }}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">ACTIVE TIME SUMMARY</p>
              <h2>Time breakdown</h2>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span style={{ fontWeight: 650 }}>Total: {formatActiveDuration(activeTimeBreakdown.totalSeconds)}</span>
              <input
                type="date"
                value={selectedDate}
                onChange={(event) => {
                  setSelectedDate(event.target.value);
                  refresh(event.target.value);
                }}
              />
            </div>
          </div>
          
          <div className="breakdown-list">
            {activeTimeBreakdown.apps.map((app) => {
              const percentage = activeTimeBreakdown.totalSeconds > 0 
                ? (app.seconds / activeTimeBreakdown.totalSeconds) * 100 
                : 0;
              return (
                <div key={app.name} className={`breakdown-item ${app.source}`}>
                  <div className="breakdown-header">
                    <div className="breakdown-info">
                      <span className={`breakdown-badge ${app.source}`}>{app.source}</span>
                      <span className="breakdown-name" title={app.name}>{app.name}</span>
                    </div>
                    <span className="breakdown-duration">{formatActiveDuration(app.seconds)}</span>
                  </div>
                  <div className="breakdown-bar-bg">
                    <div className="breakdown-bar-fill" style={{ width: `${percentage}%` }} />
                  </div>
                  {app.domains && app.domains.length > 0 && (
                    <div className="domain-breakdown">
                      {app.domains.map((dom) => (
                        <div key={dom.domain} className="domain-item">
                          <span className="domain-name" title={dom.domain}>{dom.domain}</span>
                          <span>{formatActiveDuration(dom.seconds)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {!activeTimeBreakdown.apps.length && <p className="empty">No application activity logged for this date.</p>}
          </div>
        </section>
      </div>

      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>User Settings</h2>
              <button className="close-btn" onClick={() => setShowSettings(false)}>×</button>
            </div>
            <form onSubmit={saveSettings}>
              <div className="form-group">
                <label htmlFor="pomodoro_duration">Default Pomodoro Duration (minutes)</label>
                <input
                  id="pomodoro_duration"
                  type="number"
                  min="1"
                  max="120"
                  value={settingsForm.pomodoro_duration_minutes}
                  onChange={(e) => setSettingsForm({ ...settingsForm, pomodoro_duration_minutes: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="sleep_time">Sleep Time (HH:MM)</label>
                <input
                  id="sleep_time"
                  type="time"
                  value={settingsForm.sleep_time}
                  onChange={(e) => setSettingsForm({ ...settingsForm, sleep_time: e.target.value })}
                  required
                />
                <span className="eyebrow" style={{ marginTop: "0.2rem" }}>
                  Nightly reflection trigger: {parse_sleep_trigger_display(settingsForm.sleep_time)}
                </span>
              </div>
              <div className="form-group">
                <label htmlFor="reflection_email">Reflection Email (Apple Watch Glance)</label>
                <input
                  id="reflection_email"
                  type="email"
                  placeholder="user@example.com"
                  value={settingsForm.reflection_email || ""}
                  onChange={(e) => setSettingsForm({ ...settingsForm, reflection_email: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label htmlFor="monthly_goals">Monthly Focus Goals (One per line)</label>
                <textarea
                  id="monthly_goals"
                  rows="3"
                  placeholder="Set your goals for the month here (one per line)..."
                  value={settingsForm.monthly_goals_text || ""}
                  onChange={(e) => setSettingsForm({ ...settingsForm, monthly_goals_text: e.target.value })}
                  style={{ width: "100%", background: "#111c29", color: "#eaf1f8", border: "1px solid #344a61", borderRadius: "8px", padding: "0.65rem", fontFamily: "inherit", resize: "vertical" }}
                />
              </div>
              <div className="form-group">
                <label htmlFor="core_values">Daily Rules & Core Values (One per line)</label>
                <textarea
                  id="core_values"
                  rows="6"
                  placeholder="Enter core principles (one per line)..."
                  value={settingsForm.core_values_text || ""}
                  onChange={(e) => setSettingsForm({ ...settingsForm, core_values_text: e.target.value })}
                  style={{ width: "100%", background: "#111c29", color: "#eaf1f8", border: "1px solid #344a61", borderRadius: "8px", padding: "0.65rem", fontFamily: "inherit", resize: "vertical" }}
                />
              </div>
              {settingsError && <p className="error">{settingsError}</p>}
              {settingsSuccess && <p className="success">{settingsSuccess}</p>}
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowSettings(false)}>
                  Close
                </button>
                <button type="submit" disabled={savingSettings}>
                  {savingSettings ? "Saving…" : "Save Settings"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}

function parse_sleep_trigger_display(sleepTimeStr) {
  if (!sleepTimeStr) return "22:45";
  const [h, m] = sleepTimeStr.split(":").map(Number);
  if (isNaN(h) || isNaN(m)) return "22:45";
  const total = (h * 60 + m - 15 + 1440) % 1440;
  const th = String(Math.floor(total / 60)).padStart(2, "0");
  const tm = String(total % 60).padStart(2, "0");
  return `${th}:${tm} (15m before sleep)`;
}
