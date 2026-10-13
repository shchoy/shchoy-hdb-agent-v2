import { http, HttpResponse } from "msw";

/** Where the BFF tests point PLG_API_URL; MSW stands in for plg-api there. */
export const PLG_API = "http://plg-api.test";

export const PERSONAS = [
  { staff_id: "S01", name: "Tan Wei Ling", title: "Director", dept: "PLG", role: "director" },
  { staff_id: "S04", name: "Marcus Lim", title: "Estate Manager", dept: "PLG", role: "estate_manager" },
];

export const personasApi = http.get(`${PLG_API}/personas`, () => HttpResponse.json(PERSONAS));
