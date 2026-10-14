chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "inspect") {
    const result = inspectElement(msg.x, msg.y);
    sendResponse(result);
    return true;
  }
});

function inspectElement(x, y) {
  const borderX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
  const borderY = Math.max(0, window.outerHeight - window.innerHeight - borderX);
  
  const vx = Math.round(x - window.screenX - borderX);
  const vy = Math.round(y - window.screenY - borderY);

  const el = document.elementFromPoint(vx, vy);
  if (!el) return { error: `No element found at viewport (${vx}, ${vy}) screen (${x}, ${y})` };

  const selector = generateSelector(el);
  const rect = el.getBoundingClientRect();
  const styles = window.getComputedStyle(el);

  const computedStyles = {};
  [
    "position", "display", "visibility", "zIndex", "opacity",
    "overflow", "cursor", "pointerEvents", "margin", "padding",
  ].forEach((p) => {
    computedStyles[p] = styles[p];
  });

  let reactComponents = "";
  try {
    reactComponents = getReactComponentTree(el);
  } catch (_) {}

  let reactSource = null;
  try {
    reactSource = getReactSource(el);
  } catch (_) {}

  const arrowId = el.getAttribute("data-arrow-id") || "";
  const testId =
    el.getAttribute("data-testid") ||
    el.getAttribute("data-test-id") ||
    el.getAttribute("data-test") ||
    "";
  const route = window.location.pathname || "";

  const a11y = {
    role: el.getAttribute("role") || el.tagName.toLowerCase(),
    name:
      el.getAttribute("aria-label") ||
      el.getAttribute("aria-labelledby") ||
      el.textContent?.trim()?.slice(0, 100) ||
      "",
    keyboardInteractable:
      el.tabIndex >= 0 ||
      ["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName),
  };

  const viewport = {
    width: window.innerWidth,
    height: window.innerHeight,
    scrollX: window.scrollX,
    scrollY: window.scrollY,
  };

  return {
    selector,
    elementPath: getElementPath(el),
    tagName: el.tagName.toLowerCase(),
    id: el.id,
    className:
      typeof el.className === "string" ? el.className : el.className?.baseVal || "",
    boundingBox: {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    },
    computedStyles,
    reactComponents,
    reactSource,
    arrowId,
    testId,
    route,
    pageUrl: window.location.href || "",
    accessibility: a11y,
    viewport,
    text: el.textContent?.trim()?.slice(0, 200) || "",
    href: el.href || "",
    src: el.src || "",
    innerHtml: el.innerHTML?.slice(0, 300) || "",
  };
}

function generateSelector(el) {
  if (el.id) return `#${CSS.escape(el.id)}`;
  const parts = [];
  let current = el;
  while (current && current !== document.body && current !== document.documentElement) {
    let sel = current.tagName.toLowerCase();
    if (current.id) {
      parts.unshift(`#${CSS.escape(current.id)}`);
      break;
    }
    if (current.className && typeof current.className === "string") {
      const classes = current.className
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 3);
      if (classes.length) sel += "." + classes.map(c => CSS.escape(c)).join(".");
    }
    const parent = current.parentElement;
    if (parent) {
      const sameTag = Array.from(parent.children).filter(
        (s) => s.tagName === current.tagName
      );
      if (sameTag.length > 1) {
        const idx = sameTag.indexOf(current) + 1;
        sel += `:nth-of-type(${idx})`;
      }
    }
    parts.unshift(sel);
    current = current.parentElement;
  }
  return parts.join(" > ") || el.tagName.toLowerCase();
}

function getElementPath(el) {
  const parts = [];
  let current = el;
  while (current && current !== document.documentElement) {
    let tag = current.tagName.toLowerCase();
    if (current.id) tag += `#${CSS.escape(current.id)}`;
    parts.unshift(tag);
    current = current.parentElement;
  }
  return "html > " + parts.join(" > ");
}

function getReactComponentTree(el) {
  const fiberKey = Object.keys(el).find((k) =>
    k.startsWith("__reactFiber$")
  );
  if (!fiberKey) return "";
  let fiber = el[fiberKey];
  const names = [];
  let depth = 0;
  while (fiber && depth < 30) {
    const owner = fiber._debugOwner;
    const name =
      owner?.type?.displayName ||
      owner?.type?.name ||
      fiber.type?.displayName ||
      fiber.type?.name;
    if (
      name &&
      name[0] !== name[0]?.toLowerCase() &&
      !names.includes(name)
    ) {
      names.unshift(name);
    }
    fiber = owner || fiber.return;
    depth++;
  }
  return names.join(" > ");
}

function getReactSource(el) {
  const fiberKey = Object.keys(el).find((k) => k.startsWith("__reactFiber$"));
  if (!fiberKey) return null;
  let fiber = el[fiberKey];
  let depth = 0;
  while (fiber && depth < 30) {
    const src = fiber._debugSource;
    if (src && src.fileName) {
      return {
        fileName: src.fileName,
        lineNumber: src.lineNumber,
        columnNumber: src.columnNumber,
      };
    }
    fiber = fiber._debugOwner || fiber.return;
    depth++;
  }
  return null;
}
