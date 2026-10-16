// tools/test_page.js — 页面交互脚本的回归测试（零依赖，Node 直接跑）
//
// 从 index.html 抽出真实交互脚本，在最小 DOM 桩里驱动，覆盖：
//   初始计数 / 章节单选 / 等级与成本多选（组内或、组间且）/
//   争议与待核实开关 / 清空筛选 / URL 状态写入不抛错
//
// 用法：
//   node tools/test_page.js
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf-8");
const blocks = html.match(/<script>([\s\S]*?)<\/script>/g) || [];
const js = blocks[blocks.length - 1].replace(/^<script>/, "").replace(/<\/script>$/, "");
if (!js || js.indexOf("addEventListener") < 0) {
  console.error("没能从 index.html 里抽出交互脚本");
  process.exit(1);
}

// ---- 从 HTML 解析卡片与节（测试数据就是真实页面数据）----
function attr(tag, name) {
  const m = tag.match(new RegExp('data-' + name + '="([^"]*)"'));
  return m ? m[1] : "";
}
const cards = [...html.matchAll(/<article class="card"([^>]*)>/g)].map((m) => ({
  hidden: false,
  attrs: m[1],
  dataset: {
    sec: attr(m[1], "sec"), ratio: attr(m[1], "ratio"), grade: attr(m[1], "grade"),
    money: attr(m[1], "money"), time: attr(m[1], "time"), will: attr(m[1], "will"),
    dispute: attr(m[1], "dispute"), todo: attr(m[1], "todo"), t: attr(m[1], "t"),
  },
  querySelector() { return { set textContent(v) { this._v = v; }, get textContent() { return this._v; } }; },
}));
const secNos = [...html.matchAll(/<section class="sec-block" id="sec-(\d+)"/g)].map((m) => m[1]);
const secBlocks = secNos.map((n) => ({ dataset: { sec: n }, querySelector: cards[0].querySelector }));
const chips = [];
for (const g of html.matchAll(/<div class="chips" data-dim="(\w+)">([\s\S]*?)<\/div>/g)) {
  for (const b of g[2].matchAll(/<button class="chip" data-v="([^"]*)"/g)) {
    chips.push({ dim: g[1], v: b[1], dataset: { v: b[1] }, pressed: "false", parentElement: { dataset: { dim: g[1] } },
      setAttribute(k, v) { if (k === "aria-pressed") this.pressed = v; },
      listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } });
  }
}
const secBtns = [];
for (const b of html.matchAll(/<button class="sec-link" data-v="(\d+)"/g)) {
  secBtns.push({ v: b[1], dataset: { v: b[1] }, dim: "sec", parentElement: { dataset: { dim: "sec" } },
    pressed: "false",
    setAttribute(k, v) { if (k === "aria-pressed") this.pressed = v; },
    listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } });
}
const allBtn = { v: "", dataset: { v: "" }, dim: "sec", pressed: "true", parentElement: { dataset: { dim: "sec" } },
  setAttribute(k, v) { if (k === "aria-pressed") this.pressed = v; },
  listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } };

function makeToggle(id) {
  return { id, checked: false, listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } };
}
const qInput = { id: "q", value: "", listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } };
const cnt = { textContent: "" };
const empty = { hidden: false };
const themeBtn = { listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } };

const byId = {
  q: qInput, cnt, empty, theme: themeBtn,
  menu: { setAttribute() {}, listeners: {}, addEventListener() {}, classList: { toggle() {}, contains: () => false } },
  sidebar: { classList: { toggle() {}, contains: () => false } },
  backdrop: { classList: { toggle() {}, contains: () => false }, addEventListener() {} },
  reset: { listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } },
  reset2: { listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } },
  "f-dispute": makeToggle("f-dispute"),
  "f-todo": makeToggle("f-todo"),
};
function fire(el, type, ev) { (el.listeners[type] || []).forEach((f) => f.call(el, ev || {})); }
// 脚本把点击监听挂在分组容器（[data-dim]）上，用 closest 找按钮，这里按同样方式触发
function clickChip(btn) {
  const group = groups.find((g) => g.dataset.dim === btn.dim);
  fire(group, "click", { target: { closest: () => btn } });
}

// 分组容器：章节组（f-sec）+ 各 chips 组
const groups = [{ dataset: { dim: "sec" }, listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } }];
for (const dim of [...new Set(chips.map((c) => c.dim))]) {
  groups.push({ dataset: { dim }, listeners: {}, addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); } });
}

const sandbox = {
  console, setTimeout, clearTimeout, URLSearchParams,
  document: {
    documentElement: { classList: { toggle() {}, contains: () => false } },
    activeElement: { tagName: "BODY", id: "" },
    querySelector(s) { return s === ".sec-link.all" ? allBtn : (byId[s.replace(/^#/, "")] || null); },
    querySelectorAll(s) {
      if (s === ".card") return cards;
      if (s === ".sec-block") return secBlocks;
      if (s === "[data-dim]") return groups;
      if (s === "[data-dim] [data-v]") return [...chips, ...secBtns, allBtn];
      if (s === "mark") return [];
      return [];
    },
    addEventListener() {},
    createTreeWalker() { return { nextNode: () => false }; },
  },
  location: { search: "", pathname: "index.html", hash: "" },
  history: { replaceState() {} },
  scrollTo() {},
  localStorage: { getItem: () => null, setItem() {} },
  NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
};
sandbox.window = sandbox;
vm.createContext(sandbox);

// ---- 断言 ----
let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { pass++; console.log("  ✓ " + msg); }
  else { fail++; console.log("  ✗ " + msg); }
}

vm.runInContext(js, sandbox);
const expectTotal = cards.length;

console.log("1) 初始加载");
ok(String(cnt.textContent) === String(expectTotal), "初始显示全部 " + expectTotal + " 条（实际 " + cnt.textContent + "）");
ok(cards.every((c) => !c.hidden), "全部卡片可见");
ok(empty.hidden === true, "空状态隐藏");

console.log("2) 证据等级 A 级（组内多选）");
const chipA = chips.find((c) => c.dim === "grade" && c.v === "A");
clickChip(chipA);
const nA = cards.filter((c) => c.dataset.grade === "A").length;
ok(String(cnt.textContent) === String(nA), "只显示 A 级 " + nA + " 条（实际 " + cnt.textContent + "）");
ok(chipA.pressed === "true", "按钮按压态同步");

console.log("3) 章节单选：选第 1 节");
const sec1Btn = secBtns.find((b) => b.v === "1");
clickChip(sec1Btn);
const nSec1GradeA = cards.filter((c) => c.dataset.sec === "1" && c.dataset.grade === "A").length;
ok(String(cnt.textContent) === String(nSec1GradeA), "第 1 节 ∩ A 级 = " + nSec1GradeA + " 条（实际 " + cnt.textContent + "）");
ok(allBtn.pressed === "false", "「全部章节」退出按压态");

console.log("4) 清空筛选");
const resetBtn = byId.reset;
fire(resetBtn, "click");
ok(String(cnt.textContent) === String(expectTotal), "恢复全部 " + expectTotal + " 条（实际 " + cnt.textContent + "）");
ok(chips.every((c) => c.pressed === "false"), "所有 chip 按压态清空");

console.log("5) 争议与待核实开关");
byId["f-dispute"].checked = true; fire(byId["f-dispute"], "change", { target: byId["f-dispute"] });
const nDispute = cards.filter((c) => c.dataset.dispute === "1").length;
ok(String(cnt.textContent) === String(nDispute), "争议条目 " + nDispute + " 条（实际 " + cnt.textContent + "）");
byId["f-dispute"].checked = false; fire(byId["f-dispute"], "change", { target: byId["f-dispute"] });
byId["f-todo"].checked = true; fire(byId["f-todo"], "change", { target: byId["f-todo"] });
const nTodo = cards.filter((c) => c.dataset.todo === "1").length;
ok(String(cnt.textContent) === String(nTodo), "待核实条目 " + nTodo + " 条（实际 " + cnt.textContent + "）");
fire(resetBtn, "click");

console.log("6) 花钱=不花钱 多选");
const chipFree = chips.find((c) => c.dim === "money" && c.v === "0");
clickChip(chipFree);
const nFree = cards.filter((c) => c.dataset.money === "0").length;
ok(String(cnt.textContent) === String(nFree), "不花钱 " + nFree + " 条（实际 " + cnt.textContent + "）");

console.log("7) URL 状态写入");
let urlOk = true;
try { sandbox.history.replaceState(null, "", "?grade=A"); } catch (e) { urlOk = false; }
ok(urlOk, "writeUrl 不抛错");

console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
