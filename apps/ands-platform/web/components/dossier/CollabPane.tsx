"use client";
import { useCallback, useEffect, useState } from "react";
import { auth } from "@/lib/auth";

// Collaboration pane for the dossier workspace: the dossier's task list
// (create / complete) plus the signed-in user's notification inbox, served
// by the collaboration microservice via the same-origin /api/collab proxy.

interface CollabTask {
  id: string;
  title: string;
  assignee: string;
  due_date: string | null;
  status: string;
}

interface CollabNotification {
  id: string;
  subject: string;
  body: string;
  read: boolean;
}

const BASE = "/api/collab";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const b = await res.json();
      detail = [b.title, b.detail].filter(Boolean).join(": ") || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function CollabPane({ dossierId }: { dossierId: string }) {
  const [me, setMe] = useState("");
  const [tasks, setTasks] = useState<CollabTask[]>([]);
  const [notes, setNotes] = useState<CollabNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [showInbox, setShowInbox] = useState(false);
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(
    async (user: string) => {
      try {
        const t = await j<{ tasks: CollabTask[] }>(
          `/tasks?dossier_id=${encodeURIComponent(dossierId)}`
        );
        setTasks(t.tasks);
        if (user) {
          const inbox = await j<{
            notifications: CollabNotification[];
            unread: number;
          }>(`/inbox?user=${encodeURIComponent(user)}`);
          setNotes(inbox.notifications);
          setUnread(inbox.unread);
        }
        setError("");
      } catch (e: any) {
        setError(String(e?.message || e));
      }
    },
    [dossierId]
  );

  useEffect(() => {
    let email = "";
    auth
      .me()
      .then((p) => {
        email = p.email;
        setMe(email);
        setAssignee((a) => a || email);
      })
      .catch(() => {})
      .finally(() => refresh(email));
  }, [refresh]);

  async function createTask() {
    if (!title.trim() || !assignee.trim()) return;
    setBusy(true);
    try {
      await j("/tasks", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          assignee: assignee.trim(),
          due_date: due || null,
          created_by: me,
          target_type: "dossier",
          target_id: dossierId,
          dossier_id: dossierId,
        }),
      });
      setTitle("");
      setDue("");
      await refresh(me);
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id: string, status: string) {
    try {
      await j("/tasks/status", {
        method: "POST",
        body: JSON.stringify({ id, status }),
      });
      await refresh(me);
    } catch (e: any) {
      setError(String(e?.message || e));
    }
  }

  const open = tasks.filter((t) => t.status !== "done");
  const done = tasks.length - open.length;
  // WS7: who is BLOCKED — an open task whose due date is in the past. Derived
  // from the real task store (assignee + due_date), not a hardcoded flag.
  const todayIso = new Date().toISOString().slice(0, 10);
  const overdue = open.filter((t) => t.due_date && t.due_date < todayIso);
  const assignees = Array.from(
    new Set(open.map((t) => t.assignee).filter(Boolean))
  );
  const input = {
    width: "100%",
    fontSize: 12,
    padding: "6px 8px",
    marginTop: 6,
  } as const;

  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <div className="mut" style={{ fontSize: 12 }}>Collaboration</div>
        <button
          className="ghost"
          style={{ marginLeft: "auto", fontSize: 11, padding: "3px 9px" }}
          onClick={() => setShowInbox((s) => !s)}
        >
          Inbox{unread > 0 ? ` · ${unread}` : ""}
        </button>
      </div>

      {error && (
        <div className="mut" style={{ fontSize: 11, marginTop: 6 }}>
          Collaboration unavailable — {error}
        </div>
      )}

      {showInbox && (
        <div style={{ marginTop: 8 }}>
          {notes.length === 0 && (
            <div className="mut" style={{ fontSize: 12 }}>
              No notifications yet.
            </div>
          )}
          {notes.slice(0, 5).map((n) => (
            <div
              key={n.id}
              className="mut"
              style={{ fontSize: 12, marginTop: 3 }}
            >
              {n.read ? "○" : "●"} {n.subject}
            </div>
          ))}
        </div>
      )}

      {/* WS7: assignees + blocked status for this dossier, at a glance. */}
      {open.length > 0 && (
        <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {assignees.map((a) => (
            <span key={a} className="chip" style={{ fontSize: 10 }}
              title="Assigned an open task on this dossier">
              {a}
            </span>
          ))}
          {overdue.length > 0 && (
            <span className="chip blocked" style={{ fontSize: 10 }}
              title={`${overdue.length} task(s) past due`}>
              ⛔ {overdue.length} blocked
            </span>
          )}
        </div>
      )}

      <div style={{ marginTop: 8 }}>
        {open.length === 0 && (
          <div className="mut" style={{ fontSize: 12 }}>
            No open tasks for this dossier.
          </div>
        )}
        {open.map((t) => {
          const isOverdue = !!t.due_date && t.due_date < todayIso;
          return (
          <div
            key={t.id}
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 6,
              fontSize: 12,
              marginTop: 4,
            }}
          >
            <span style={{ flex: 1 }}>
              {t.title}
              <span className="mut">
                {" "}— {t.assignee}
                {t.due_date ? ` · due ${t.due_date}` : ""}
              </span>
              {" "}
              <span
                className={`chip ${isOverdue ? "blocked" : ""}`}
                style={{ fontSize: 10 }}
              >
                {isOverdue ? "overdue" : t.status.replace("_", " ")}
              </span>
            </span>
            {t.status === "open" && (
              <button
                className="ghost"
                style={{ fontSize: 11, padding: "2px 8px" }}
                onClick={() => setStatus(t.id, "in_progress")}
                title="Mark in progress"
              >
                Start
              </button>
            )}
            <button
              className="ghost"
              style={{ fontSize: 11, padding: "2px 8px" }}
              onClick={() => setStatus(t.id, "done")}
            >
              Done
            </button>
          </div>
          );
        })}
        {done > 0 && (
          <div className="mut" style={{ fontSize: 11, marginTop: 4 }}>
            {done} completed
          </div>
        )}
      </div>

      <input
        style={input}
        placeholder="New task title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <input
        style={input}
        placeholder="Assignee (email)"
        value={assignee}
        onChange={(e) => setAssignee(e.target.value)}
      />
      <input
        style={input}
        type="date"
        value={due}
        onChange={(e) => setDue(e.target.value)}
      />
      <button
        className="ghost"
        style={{ marginTop: 8, fontSize: 12, padding: "6px 10px" }}
        onClick={createTask}
        disabled={busy || !title.trim() || !assignee.trim()}
      >
        {busy ? "Adding…" : "Add task"}
      </button>
    </div>
  );
}
