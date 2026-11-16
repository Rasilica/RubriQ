import {element} from "/review-assets/primitives.mjs";
import {rollingNumber} from "./lucian.mjs";

// Count tile used by the results page and the prepare result step.
export function statTile(tone,label,value,caption) {
  const tile=element("article",`stat-tile ${tone}`);
  if(tone === "critical") {
    for(const name of ["orb","ring"]) {const decor=element("img",`stat-${name}`);decor.src=`/brand-assets/stat-${name}.svg`;decor.alt="";tile.append(decor);}
  }
  const top=element("p","stat-top");const dot=element("img","stat-dot");dot.src=tone === "default" ? "/brand-assets/stat-dot.svg" : "/brand-assets/stat-dot-attention.svg";dot.alt="";dot.width=8;dot.height=8;
  top.append(dot,element("span","",label));
  const amount=element("p","stat-value");amount.append(rollingNumber(value,`${value}건`),element("span","stat-unit","건"));
  const body=element("div","stat-body");body.append(amount,element("p","stat-caption",caption));
  tile.append(top,body);
  return tile;
}
