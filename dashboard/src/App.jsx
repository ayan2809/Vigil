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


export default function App() {
  const [selectedDate, setSelectedDate] = useState(today());
  const [tasks, setTasks] = useState([]);
  const [activeTimeBreakdown, setActiveTimeBreakdown] = useState({ totalSeconds: 0, apps: [] });
  const [summary, setSummary] = useState([]);
  const [timer, setTimer] = useState({ status: "idle", phase: "work", remaining_seconds: 0 });
  const [userSettings, setUserSettings] = useState({ pomodoro_duration_minutes: 25, sleep_time: "23:00", reflection_email: "" });
  const [title, setTitle] = useState("");
  const [estimate, setEstimate] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  // Settings modal states
  const [showSettings, setShowSettings] = useState(false);
  const [settingsForm, setSettingsForm] = useState({ pomodoro_duration_minutes: 25, sleep_time: "23:00", reflection_email: "" });
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSuccess, setSettingsSuccess] = useState("");
  const [settingsError, setSettingsError] = useState("");

  async function refresh(date = selectedDate) {
    setLoading(true);
    setError("");
    try {
      const [nextTasks, nextSummaryBreakdown, nextSummary, nextTimer, nextSettings] = await Promise.all([
        request("/tasks"),
        request(`/active-time-summary?date=${encodeURIComponent(date)}`),
        request("/activity/summary?days=28"),
        request("/pomodoro"),
        request("/settings"),
      ]);
      setTasks(nextTasks);
      setActiveTimeBreakdown(nextSummaryBreakdown);
      setSummary(nextSummary.days);
      setTimer(nextTimer);
      if (nextSettings) {
        setUserSettings(nextSettings);
        setSettingsForm({
          pomodoro_duration_minutes: nextSettings.pomodoro_duration_minutes || 25,
          sleep_time: nextSettings.sleep_time || "23:00",
          reflection_email: nextSettings.reflection_email || "",
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

  async function saveSettings(e) {
    e.preventDefault();
    setSavingSettings(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      const updated = await request("/settings", {
        method: "PUT",
        body: JSON.stringify({
          pomodoro_duration_minutes: Number(settingsForm.pomodoro_duration_minutes),
          sleep_time: settingsForm.sleep_time,
          reflection_email: settingsForm.reflection_email.trim() || null,
        }),
      });
      setUserSettings(updated);
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
            <p className="eyebrow">{timer.phase} session · {timer.status}</p>
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

      <div className="columns">
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
