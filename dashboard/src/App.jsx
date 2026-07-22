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

export default function App() {
  const [selectedDate, setSelectedDate] = useState(today());
  const [tasks, setTasks] = useState([]);
  const [activeTimeBreakdown, setActiveTimeBreakdown] = useState({ totalSeconds: 0, apps: [] });
  const [summary, setSummary] = useState([]);
  const [timer, setTimer] = useState({ status: "idle", phase: "work", remaining_seconds: 0 });
  const [title, setTitle] = useState("");
  const [estimate, setEstimate] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh(date = selectedDate) {
    setLoading(true);
    setError("");
    try {
      const [nextTasks, nextSummaryBreakdown, nextSummary, nextTimer] = await Promise.all([
        request("/tasks"),
        request(`/active-time-summary?date=${encodeURIComponent(date)}`),
        request("/activity/summary?days=28"),
        request("/pomodoro"),
      ]);
      setTasks(nextTasks);
      setActiveTimeBreakdown(nextSummaryBreakdown);
      setSummary(nextSummary.days);
      setTimer(nextTimer);
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
      await request("/pomodoro/start", {
        method: "POST",
        body: JSON.stringify({ task_id: task.id, duration_seconds: 1500 }),
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

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">LOCAL ACTIVITY & FOCUS</p>
          <h1>Vigil</h1>
        </div>
        <button className="secondary" onClick={() => refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      <div className="top-row">
        <section className="timer card" style={{ flex: 1.6, marginBottom: 0 }}>
          <div>
            <p className="eyebrow">{timer.phase} session · {timer.status}</p>
            <p className="clock">{formatDuration(timer.remaining_seconds)}</p>
          </div>
          <div className="actions">
            {timer.status === "idle" && <button onClick={() => timerAction("/pomodoro/start", { duration_seconds: 1500 })}>Start focus</button>}
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
              title={
                !day.total_laptop_time_seconds && !day.total_focus_time_seconds
                  ? "0m / 0m"
                  : `${formatHoursMins(day.total_focus_time_seconds)} / ${formatHoursMins(day.total_laptop_time_seconds)}`
              }
              style={{ opacity: day.event_count ? 0.25 + (day.event_count / maxEvents) * 0.75 : 0.08 }}
            >
              <span className="tooltip-text">
                {!day.total_laptop_time_seconds && !day.total_focus_time_seconds
                  ? "0m / 0m"
                  : `${formatHoursMins(day.total_focus_time_seconds)} / ${formatHoursMins(day.total_laptop_time_seconds)}`}
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
    </main>
  );
}
