import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/**
 * One MSW server for every test; each test installs its own handlers with `server.use`. The handlers given here
 * survive `resetHandlers`: an officer has no conversation groups (#100) unless a test says otherwise.
 */
export const server = setupServer(http.get("/api/groups", () => HttpResponse.json([])));
