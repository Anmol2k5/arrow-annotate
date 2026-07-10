chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "inspect") {
    const result = inspectElement(msg.x, msg.y);
    sendResponse(result);
    return true;
  } else if (msg.type === "start_annotation_mode") {
    startAnnotationMode(sendResponse);
    return true; // Keep message channel open for async response
  }
});

let overlayElement = null;
let isDrawing = false;
let strokePoints = [];

function startAnnotationMode(sendResponse) {
  if (overlayElement) overlayElement.remove();

  const canvas = document.createElement("canvas");
  canvas.id = "arrow-annotation-overlay";
  Object.assign(canvas.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "100vw",
    height: "100vh",
    zIndex: "2147483647",
    background: "transparent",
    cursor: "crosshair",
    pointerEvents: "auto",
  });

  const dpr = window.devicePixelRatio || 1.0;
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  overlayElement = canvas;
  document.documentElement.appendChild(canvas);

  canvas.addEventListener("pointerdown", (e) => {
    isDrawing = true;
    strokePoints = [{ x: e.clientX, y: e.clientY }];
    drawStroke();
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!isDrawing) return;
    strokePoints.push({ x: e.clientX, y: e.clientY });
    drawStroke();
  });

  canvas.addEventListener("pointerup", (e) => {
    if (!isDrawing) return;
    isDrawing = false;

    const vx = e.clientX;
    const vy = e.clientY;

    // Temporarily disable overlay interactions to capture element underneath
    canvas.style.pointerEvents = "none";
    const elements = document.elementsFromPoint(vx, vy);
    const targetElement = elements.find(el => el !== canvas && el.id !== "arrow-annotation-overlay");

    let elementContext = {};
    if (targetElement) {
      elementContext = extractElementDetails(targetElement, vx, vy);
    } else {
      elementContext = { error: `No element resolved at viewport (${vx}, ${vy})` };
    }

    canvas.remove();
    overlayElement = null;

    const viewport = {
      width: window.innerWidth,
      height: window.innerHeight,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      devicePixelRatio: dpr,
      zoom: window.visualViewport ? window.visualViewport.scale : 1.0
    };

    // Collect iframe details if present in the page
    const iframeDetails = Array.from(document.querySelectorAll("iframe")).map(f => {
      const rect = f.getBoundingClientRect();
      return {
        src: f.src,
        boundingBox: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        }
      };
    });

    const page = {
      route: window.location.pathname,
      shadowDomExists: document.querySelectorAll("*").length > 0, // basic check
      iframes: iframeDetails
    };

    sendResponse({
      viewport,
      element: elementContext,
      page
    });
  });

  function drawStroke() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (strokePoints.length < 2) return;

    // Neon glow render (simulates PyQt neon line)
    ctx.strokeStyle = "rgba(167, 139, 250, 0.15)";
    ctx.lineWidth = 16;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(strokePoints[0].x, strokePoints[0].y);
    for (let i = 1; i < strokePoints.length; i++) {
      ctx.lineTo(strokePoints[i].x, strokePoints[i].y);
    }
    ctx.stroke();

    ctx.strokeStyle = "rgba(167, 139, 250, 0.45)";
    ctx.lineWidth = 8;
    ctx.stroke();

    ctx.strokeStyle = "rgba(230, 220, 255, 1.0)";
    ctx.lineWidth = 3;
    ctx.stroke();
  }
}

function inspectElement(x, y) {
  const borderX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
  const borderY = Math.max(0, window.outerHeight - window.innerHeight - borderX);

  const vx = Math.round(x - window.screenX - borderX);
  const vy = Math.round(y - window.screenY - borderY);

  const el = document.elementFromPoint(vx, vy);
  if (!el) return { error: `No element found at viewport (${vx}, ${vy}) screen (${x}, ${y})` };

  return extractElementDetails(el, vx, vy);
}

function extractElementDetails(el, vx, vy) {
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

  // Check if inside an iframe
  let iframeInfo = null;
  if (window.self !== window.top) {
    iframeInfo = {
      inIframe: true,
      url: window.location.href,
      frameWidth: window.innerWidth,
      frameHeight: window.innerHeight
    };
  }

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
    accessibility: a11y,
    text: el.textContent?.trim()?.slice(0, 200) || "",
    href: el.href || "",
    src: el.src || "",
    innerHtml: el.innerHTML?.slice(0, 300) || "",
    shadowPath: getShadowPath(el),
    iframeInfo
  };
}

function generateSelector(el) {
  if (el.getAttribute("data-arrow-id")) return `[data-arrow-id="${CSS.escape(el.getAttribute("data-arrow-id"))}"]`;
  if (el.getAttribute("data-testid")) return `[data-testid="${CSS.escape(el.getAttribute("data-testid"))}"]`;
  if (el.id) return `#${CSS.escape(el.id)}`;
  if (el.getAttribute("aria-label")) return `[aria-label="${CSS.escape(el.getAttribute("aria-label"))}"]`;

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
        .filter(c => c && !c.includes(":") && !/^(p|m|w|h|flex|grid|bg|text|border|rounded|shadow|opacity|z|cursor|pointer)-/.test(c))
        .map(c => CSS.escape(c));
      if (classes.length) sel += "." + classes.slice(0, 2).join(".");
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
  return parts.join(" > ");
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

function getShadowPath(el) {
  const path = [];
  let current = el;
  while (current) {
    if (current.parentNode instanceof ShadowRoot) {
      path.unshift(current.parentNode.host.tagName.toLowerCase() + "::shadow-root");
      current = current.parentNode.host;
    } else {
      current = current.parentNode;
    }
  }
  return path.join(" > ");
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
    fiber = owner;
    depth++;
  }
  return names.join(" > ");
}
