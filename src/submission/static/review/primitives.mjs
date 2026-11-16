export function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

export function button(label, action, variant = "") {
  const node = element("button", `button ${variant}`, label);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

export function badge(text, info = false) {
  return element("span", `badge${info ? " info" : ""}`, text);
}

export function setReadingText(node,text) {
  node.replaceChildren(...readingSegments(text).map((part)=>part.keepTogether ? element("span","reading-phrase",part.text) : document.createTextNode(part.text)));
  return node;
}

export function readingElement(tag,className,text) {
  return setReadingText(element(tag,className),text);
}

export function field({ id, label, value = "", options, multiline = false, help, required = false, onChange }) {
  const wrapper = element("div", "field");
  const caption = element("label", "", label);
  caption.htmlFor = id;
  const control = element(options ? "select" : multiline ? "textarea" : "input", "control");
  control.id = id;
  control.required = required;
  if (options) {
    for (const [key, title] of options) {
      const option = element("option", "", title);
      option.value = key;
      control.append(option);
    }
  } else if (multiline) {
    control.rows = 3;
    control.maxLength = 2000;
  } else {
    control.type = "text";
    control.maxLength = 2000;
  }
  control.value = value;
  control.addEventListener(options ? "change" : "input", () => onChange(control.value));
  wrapper.append(caption, control);
  if (help) {
    const hint = readingElement("p", "help", help);
    hint.id = `${id}-help`;
    control.setAttribute("aria-describedby", hint.id);
    wrapper.append(hint);
  }
  return wrapper;
}
import {readingSegments} from "./state.mjs";
