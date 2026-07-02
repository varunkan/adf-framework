// Turns an HTTP failure into a message a regulatory user can act on.
// Panel finding (4 flows): "the API failure error message is a bit too raw".
// Our services already write human 4xx problem details — pass those through;
// wrap everything else in plain language with a next step.
export function friendlyError(status: number, detail: string): string {
  const d = (detail || "").trim();
  const looksHuman = d && !/^\d{3}$/.test(d) && !/^[A-Z_]+$/.test(d);
  switch (true) {
    case status === 401:
      return "Your session has ended — please sign in again.";
    case status === 403:
      return "You don't have access to that in this workspace.";
    case status === 404:
      return "That item isn't in this workspace (it may have been renamed or deleted). Refresh the list and try again.";
    case status === 409:
      return looksHuman ? d : "That conflicts with something that already exists.";
    case status === 422:
      return looksHuman ? d : "Some of the entered information isn't valid — check the highlighted fields.";
    case status === 429:
      return "The service is catching its breath — wait a few seconds and try again.";
    case status >= 500:
      return "Something went wrong on our side — nothing you entered was lost. Try again; if it keeps happening, the service log has the details."
        + (looksHuman ? ` (${d})` : "");
    case status === 0:
      return "Can't reach the server — check that ANDS Studio's services are running, then try again.";
    default:
      return looksHuman ? d : `Unexpected error (${status}). Try again.`;
  }
}
