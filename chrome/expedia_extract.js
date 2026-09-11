// Run on an Expedia Hotel-Search results page (via the Claude Chrome extension's JavaScript tool).
// Scrolls to load results, then returns a compact list: {n: name, p: nightly price (pre-tax), t: 'hotel'|'vr'}.
// Only named competitors (COMPS) and vacation rentals are returned, to keep the daily payload small.
// The Cedar's own rooms are dropped.
async () => {
  const COMPS = [
    "cedar point's express hotel","fairfield by marriott inn & suites sandusky","springhill suites by marriott sandusky",
    "tru by hilton sandusky","holiday inn express & suites sandusky","hampton inn & suites sandusky","comfort inn sandusky",
    "best western plus sandusky","quality inn & suites sandusky","sleep inn sandusky","country inn & suites by radisson, sandusky",
    "la quinta inn by wyndham sandusky","south shore inn","cedar stables inn","our guest inn and suites","south beach resort hotel",
    "fairfield by marriott port clinton","holiday inn express & suites port clinton","sleep inn & suites port clinton",
    "best western port clinton","country inn & suites by radisson, port clinton","commodore perry inn",
    "quality inn port clinton waterfront","anchor bay inn"
  ];
  const norm = s => (s||"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();
  const COMPN = COMPS.map(norm);
  for (let i=0;i<8;i++){
    window.scrollBy(0, 3000); await new Promise(r=>setTimeout(r,1000));
    const b=[...document.querySelectorAll('button')].find(x=>/show more/i.test(x.innerText));
    if(b){ b.click(); await new Promise(r=>setTimeout(r,2500)); }
  }
  const cards=[...document.querySelectorAll('[data-stid="lodging-card-responsive"]')];
  const out=[]; const seen=new Set();
  for (const c of cards){
    const t=c.innerText||"";
    const h=c.querySelector('h3, h4');
    const name=(h?h.innerText:t.split('\n').find(l=>l.trim().length>3)||"").trim();
    const m=t.match(/\$([\d,]+)\s*nightly/); if(!m) continue;
    const price=parseInt(m[1].replace(/,/g,''),10); if(!price) continue;
    const n=norm(name); if(!n || seen.has(n)) continue;
    if (/the cedar|bloom where/.test(n)) continue;
    const isComp = COMPN.some(k=>n.includes(k));
    const isVR = /vacation rental|entire (home|house|apartment|condo|cabin|cottage)|sleeps \d|bedrooms?/i.test(t) && !/hotel|inn|motel|resort|lodge/i.test(name);
    if (isComp) { out.push({n:name, p:price, t:'hotel'}); seen.add(n); }
    else if (isVR) { out.push({n:name.slice(0,60), p:price, t:'vr'}); seen.add(n); }
  }
  return {count: cards.length, items: out};
}
