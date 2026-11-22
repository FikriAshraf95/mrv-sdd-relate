// Empty, loading and error states, one look for every view. Text only.
import { h } from "./dom.js";

export const loading = (text = "Loading…") => h("div", { class: "state loading", role: "status" }, h("span", { class: "spin" }), text);
export const empty = (text) => h("div", { class: "state empty" }, text);
export const failure = (text) => h("div", { class: "state error", role: "alert" }, text);
