"""Renderer-owned, offline presentation assets. No supplied data is executable."""

STYLE = r"""
:root{color-scheme:light;--ink:#192f3b;--muted:#526773;--line:#d7e1e6;--paper:#fff;
--wash:#f2f6f7;--accent:#076c73;--soft:#e3f3f0;--warn:#835a14;--warn-bg:#fff8e8}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:1rem}
body{margin:0;background:var(--wash);color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif}
a{color:var(--accent);text-underline-offset:3px}a:hover{color:#00474b}
a:focus-visible,summary:focus-visible{outline:3px solid #d56c21;outline-offset:4px;border-radius:2px}
.skip{position:absolute;left:1rem;top:-5rem;padding:.6rem;background:white;z-index:2}.skip:focus{top:1rem}
header{background:#163945;color:#fff;padding:3rem max(1.5rem,calc((100vw - 1120px)/2)) 2.2rem}
header .eyebrow{font-size:.8rem;letter-spacing:.16em;text-transform:uppercase;color:#9dd7d2}
h1{font-size:clamp(1.8rem,4vw,2.8rem);line-height:1.2;margin:.55rem 0 .8rem;overflow-wrap:anywhere}
header p{max-width:74ch;color:#d1e3e8;margin:.4rem 0}
nav{display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;margin-top:1.5rem}nav a{color:#c5f2e9;font-size:.9rem}
main{max-width:1180px;margin:0 auto;padding:1.5rem 1.5rem 3rem}
section{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:1.6rem 1.8rem;
margin-bottom:1.1rem}
h2{font-size:1.45rem;line-height:1.3;margin:0 0 1rem;letter-spacing:-.025em}
h3{font-size:1.06rem;margin:1.5rem 0 .6rem}p{margin:.6rem 0}small,.muted{color:var(--muted);font-size:.875rem}
.section-intro{color:var(--muted);max-width:82ch}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem}
.metric{padding:1rem;background:var(--wash);border-radius:8px}.metric strong{display:block;font-size:1.4rem;
line-height:1.35}
.metric .label{font-size:.8rem;color:var(--muted)}.confidence{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0}
.badge{display:inline-block;padding:.18rem .65rem;border-radius:20px;background:var(--soft);font-size:.84rem}
.notice{border-left:3px solid #c99137;padding:.65rem 1rem;background:var(--warn-bg);margin:1rem 0}
.notice h3{margin:0}.notice ul{margin:.4rem 0;padding-left:1.2rem}.notice li{margin:.2rem 0}
.table-wrap{overflow-x:auto;margin:.7rem 0}table{border-collapse:collapse;width:100%;font-size:.9rem;text-align:left}
caption{text-align:left;font-weight:650;padding:.4rem 0}th{font-size:.75rem;text-transform:uppercase;
letter-spacing:.045em;
color:var(--muted);background:var(--wash)}th,td{padding:.7rem .65rem;vertical-align:top;
border-bottom:1px solid var(--line)}
td{overflow-wrap:anywhere}tr:last-child td{border-bottom:0}.evidence-link{font-size:.78rem;white-space:nowrap}
.record-details{margin:0;min-width:8rem}.record-details summary{font-size:.8rem}
details{border:1px solid var(--line);border-radius:7px;margin:.65rem 0;background:var(--paper)}
summary{cursor:pointer;padding:.65rem .85rem;font-weight:550;color:var(--accent);overflow-wrap:anywhere}
summary::marker{color:var(--accent)}details[open]>summary{border-bottom:1px solid var(--line)}
.detail-body{padding:.8rem 1rem}td details{border:0;background:transparent}td summary{padding:0 .2rem}
td details[open]>summary{padding-bottom:.5rem}td .detail-body{padding:.4rem .1rem}
dl{display:grid;grid-template-columns:minmax(8rem,1fr) minmax(0,3fr);gap:.5rem 1rem;margin:.25rem 0}
dt{font-weight:600;font-size:.85rem}dd{margin:0;min-width:0;overflow-wrap:anywhere}dd ul{padding-left:1.2rem;margin:0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;background:var(--wash);padding:1rem;
border-radius:5px;
font: .8rem/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:2;max-height:32rem;overflow:auto}
code{font: .85em ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
.provenance{border-top:1px solid var(--line);margin-top:.8rem;padding-top:.65rem;
font-size:.85rem}.hash{word-break:break-all}
.record-list{padding-left:1.4rem}.record-list li{padding:.25rem 0}.record-list .evidence-link{margin-left:.6rem}
.deployment-groups{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.8rem}
.deployment-group{background:var(--wash);padding:1rem;border:1px solid var(--line);border-radius:8px}
.deployment-group h3{margin:0 0 .5rem}.deployment-group ul{margin:0;padding-left:1.1rem}
.startup{counter-reset:steps;display:flex;flex-wrap:wrap;gap:.6rem;list-style:none;padding:0}
.startup li{border:1px solid var(--line);border-radius:6px;padding:.45rem .7rem;background:var(--wash)}
.startup li::before{counter-increment:steps;content:counter(steps) '. ';font-weight:bold;color:var(--accent)}
.language-name{font-weight:600}meter{width:100%;min-width:6rem;height:1rem;accent-color:var(--accent)}
.graph{background:var(--wash);padding:1rem;border-radius:8px;margin:1rem 0;overflow:auto}
.graph svg{display:block;width:100%;min-width:540px;height:auto}.graph text{font:12px system-ui,sans-serif;
fill:var(--ink)}
.graph .node{fill:#fff;stroke:#438b8c;stroke-width:1.5}.graph .edge{fill:none;stroke:#6b808a;stroke-width:1.5}
.graph figcaption{font-size:.82rem;color:var(--muted);
margin-top:.5rem}.target:target,details:target{outline:3px solid #cc8c26}
footer{max-width:1120px;margin:0 auto 2rem;padding:0 1.5rem;font-size:.8rem;color:var(--muted)}
@media(max-width:780px){.metrics{grid-template-columns:repeat(2,1fr)}.deployment-groups{grid-template-columns:1fr}
section{padding:1.2rem}main{padding:.8rem}header{padding:2rem 1.2rem}dl{grid-template-columns:1fr;gap:.25rem}
dd{margin-bottom:.5rem}th,td{padding:.5rem}.metric strong{font-size:1.2rem}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:10pt}header{background:white;color:#192f3b;padding:0 0 1rem}
header p,header .eyebrow{color:#526773}nav,.skip{display:none}main{max-width:none;padding:0}
section{border:0;border-top:1px solid #bbb;border-radius:0;padding:1rem 0;break-inside:auto}
details{break-inside:auto}details:not([open])>:not(summary){display:block!important}
details::details-content{content-visibility:visible!important}pre{max-height:none;overflow:visible}
a{color:#192f3b}.table-wrap{overflow:visible}table{font-size:9pt}tr,figure,.metric{break-inside:avoid}
.graph svg{min-width:0}.metrics{grid-template-columns:repeat(4,1fr)}footer{margin:0;padding:0}}
"""

SCRIPT = r"""
'use strict';
(() => {
  const reveal = () => {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); }
    catch (_) { return; }
    if (!target) return;
    let ancestor = target;
    while (ancestor) {
      if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    target.scrollIntoView({block: 'start'});
  };
  addEventListener('hashchange', reveal);
  reveal();
  let closedBeforePrint = [];
  addEventListener('beforeprint', () => {
    closedBeforePrint = Array.from(document.querySelectorAll('details:not([open])'));
    closedBeforePrint.forEach(detail => { detail.open = true; });
  });
  addEventListener('afterprint', () => {
    closedBeforePrint.forEach(detail => { detail.open = false; });
    closedBeforePrint = [];
  });
})();
"""
