(() => {
  // Every lookup in this file is a stable hook (drift-coverage Decision 4):
  // an ARIA role, an accessible name, an aria-controls relationship, a form
  // action or field name, an href, or one of the four content data
  // attributes (`data-product`, `data-product-name`, `data-category`,
  // `data-chat-prompt`). No behaviour marker, no covered id or class, and the
  // script never writes a `data-*` attribute or an id to the DOM: state lives
  // in `is-*` classes, `hidden` and `aria-*`, and classes are changed only
  // through `classList`, never by assigning `className`.
  const SESSION_COOKIE = "session_id";
  const SESSION_COOKIE_DAYS = 30;
  const CART_ENDPOINT = "/api/cart";
  const CART_ITEMS_ENDPOINT = "/api/cart/items";
  const SEARCH_RESULTS_ENDPOINT = "/search/results";
  const SEARCH_SUGGEST_ENDPOINT = "/api/search/suggest";
  const AUTH_STORAGE_KEY = "flowline_auth_state";
  const THEME_STORAGE_KEY = "flowline_theme";
  const THEME_DARK_CLASS = "theme-dark";
  const CHAT_BODY_OPEN_CLASS = "has-chat-open";

  const PRIMARY_NAV_SELECTOR = 'nav[aria-label="Primary navigation"]';
  const NAV_TOGGLE_SELECTOR = ":scope > button[aria-controls]";
  const STATUS_REGION_SELECTOR = '[role="status"]';
  const LOGIN_BUTTON_SELECTOR = 'button[aria-haspopup="dialog"]';
  const ACCOUNT_TRIGGER_SELECTOR = "button[aria-expanded][aria-controls]";
  const LOGIN_CLOSE_LABEL = "Close login form";
  const LOGOUT_LABEL = "Log out";
  const ADDRESSES_LABEL = "Saved addresses";
  const PAYMENTS_LABEL = "Payment methods";
  const ORDERS_LABEL = "Recent orders";
  const CHECKOUT_FORM_SELECTOR = 'form[action="/checkout"]';
  const CHAT_LAUNCHER_SELECTOR = 'body > button[aria-haspopup="dialog"][aria-controls]';
  const CHAT_CLOSE_LABEL = "Close AI assistant";
  const CHAT_LOG_SELECTOR = '[role="log"]';
  const CHAT_TEXTAREA_SELECTOR = 'textarea[name="question"]';
  const SEARCH_FORM_SELECTOR = 'form[role="search"]';
  const SEARCH_INPUT_SELECTOR = 'input[name="query"]';
  const SEARCH_REGION_SELECTOR = '[role="region"][aria-label="Search results"]';
  const MIN_PRICE_SLIDER_SELECTOR = 'input[type="range"][aria-label="Minimum price"]';
  const MAX_PRICE_SLIDER_SELECTOR = 'input[type="range"][aria-label="Maximum price"]';
  const OWN_TEMPLATES_SELECTOR = ":scope > template";
  const OPTION_SELECTOR = '[role="option"]';

  // Turns an error response's `detail` into readable text. FastAPI sends a
  // string for HTTPException and an array of `{loc, msg, type}` objects for
  // validation errors; `new Error(array)` would render as "[object Object]".
  function errorText(detail, fallback) {
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) => (entry && typeof entry.msg === "string" ? entry.msg : ""))
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
    return fallback;
  }

  const FLASH_STATE_CLASSES = ["is-success", "is-error", "is-info"];
  const MOBILE_NAV_BREAKPOINT = 600;
  const mobileNavMediaQuery =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT}px)`)
      : null;

  // "Already bound" bookkeeping lives in memory, never in the DOM
  // (Decision 4): a marker attribute or an `is-bound` class would be a
  // drift-proof locator.
  const mobileNavBound = new WeakSet();
  const themeBound = new WeakSet();
  const chatBound = new WeakSet();
  const chatPromptBound = new WeakSet();

  let flashTimer;
  let authState = null;
  let sessionId = ensureSessionId();
  let chatHistory = [];
  let isChatOpen = false;
  let chatKeydownListenerAttached = false;
  let currentTheme = "light";

  window.analyticsTrack =
    window.analyticsTrack ||
    function analyticsTrack(eventName, payload = {}) {
      console.log("[analytics]", eventName, payload);
    };

  function getCookie(name) {
    const cookieString = document.cookie;
    if (!cookieString) return null;
    const cookies = cookieString.split(";").map((c) => c.trim());
    const target = cookies.find((row) => row.startsWith(`${name}=`));
    return target ? decodeURIComponent(target.split("=")[1]) : null;
  }

  function setCookie(name, value, days) {
    const expires = new Date(Date.now() + days * 86400000).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(
      value,
    )}; expires=${expires}; path=/; SameSite=Lax`;
  }

  function ensureSessionId() {
    let existing = getCookie(SESSION_COOKIE);
    if (!existing) {
      if (typeof crypto !== "undefined" && crypto.randomUUID) {
        existing = crypto.randomUUID();
      } else {
        existing = `sess-${Math.random().toString(36).slice(2, 12)}`;
      }
      setCookie(SESSION_COOKIE, existing, SESSION_COOKIE_DAYS);
    }
    return existing;
  }

  function loadAuth() {
    try {
      const raw = localStorage.getItem(AUTH_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || !parsed.user || !parsed.access_token) {
        localStorage.removeItem(AUTH_STORAGE_KEY);
        return null;
      }
      return parsed;
    } catch {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      return null;
    }
  }

  function saveAuth(data) {
    authState = data;
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(data));
  }

  function clearAuth() {
    authState = null;
    localStorage.removeItem(AUTH_STORAGE_KEY);
    updateAuthUI();
    applyAuthToCheckout();
  }

  function ownTemplates(element) {
    return element ? element.querySelectorAll(OWN_TEMPLATES_SELECTOR) : [];
  }

  function cloneTemplate(template) {
    const root = template?.content?.firstElementChild;
    return root ? root.cloneNode(true) : null;
  }

  // ---------------------------------------------------------------------
  // The confirmation region: the only element with the role="status"
  // attribute (task 8.2). Its state is `is-visible` plus one `is-*` variant.
  // ---------------------------------------------------------------------

  function getStatusRegion() {
    return document.querySelector(STATUS_REGION_SELECTOR);
  }

  function showFlash(message, variant = "info") {
    const region = getStatusRegion();
    if (!region) return;
    const state = `is-${variant}`;
    region.textContent = message;
    region.classList.remove(...FLASH_STATE_CLASSES);
    region.classList.add("is-visible", FLASH_STATE_CLASSES.includes(state) ? state : "is-info");
    clearTimeout(flashTimer);
    flashTimer = window.setTimeout(() => {
      region.classList.remove("is-visible", ...FLASH_STATE_CLASSES);
      region.textContent = "";
    }, 3500);
  }

  // ---------------------------------------------------------------------
  // Cart badge and add to cart
  // ---------------------------------------------------------------------

  function getCartBadge() {
    return document.querySelector(`nav a[href="/cart"] [aria-live]`);
  }

  function updateCartBadge(state) {
    const counter = getCartBadge();
    if (!counter) return;
    const items = Array.isArray(state?.items) ? state.items : [];
    const quantity = items.reduce(
      (total, item) => total + Number(item?.quantity ?? 0),
      0,
    );
    if (quantity > 0) {
      counter.textContent = quantity;
      counter.classList.add("is-visible");
    } else {
      counter.textContent = "";
      counter.classList.remove("is-visible");
    }
  }

  async function fetchCartState() {
    try {
      const response = await fetch(`${CART_ENDPOINT}/`, {
        headers: {
          "X-Session-ID": sessionId,
        },
      });
      if (!response.ok) return;
      const data = await response.json();
      updateCartBadge(data);
    } catch (error) {
      console.warn("Unable to refresh cart state", error);
    }
  }

  async function addToCart(button) {
    const productId = Number(button.dataset.product);
    if (!Number.isFinite(productId)) {
      showFlash("Invalid product identifier.", "error");
      return;
    }
    // No template renders a quantity attribute, so one item per click.
    const quantity = 1;
    const productName = button.dataset.productName || "Unknown product";
    // The card variants render the button inside the card's <article>; the
    // detail page's call to action does not sit in one.
    const source = button.closest("article") ? "product_card" : "cta";

    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(CART_ITEMS_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Session-ID": sessionId,
        },
        body: JSON.stringify({ product_id: productId, quantity }),
      });

      if (!response.ok) {
        const detail = await response
          .json()
          .then((body) => body?.detail)
          .catch(() => null);
        throw new Error(errorText(detail, "Unable to add item to cart."));
      }

      const cartState = await response.json();
      updateCartBadge(cartState);
      showFlash(`${productName} added to cart.`, "success");
      window.analyticsTrack("add_to_cart", {
        product_id: productId,
        product_name: productName,
        quantity,
        source,
      });
    } catch (error) {
      console.error(error);
      showFlash(error.message || "Unable to add item to cart.", "error");
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  function formatCurrency(value) {
    try {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
    } catch (_error) {
      const num = Number(value) || 0;
      return `$${num.toFixed(2)}`;
    }
  }

  // ---------------------------------------------------------------------
  // Search: the results come from the server fragment (task 9.2)
  // ---------------------------------------------------------------------

  function getSearchRegion() {
    const region = document.querySelector(SEARCH_REGION_SELECTOR);
    if (!region) return null;
    const clearButton = region.querySelector("button[aria-controls]");
    if (!clearButton) return null;
    const list = document.getElementById(clearButton.getAttribute("aria-controls"));
    if (!list) return null;
    return { region, clearButton, list };
  }

  function attachSearch() {
    const forms = document.querySelectorAll(SEARCH_FORM_SELECTOR);
    if (!forms.length) return;

    const clearResults = () => {
      const elements = getSearchRegion();
      if (elements) {
        elements.region.hidden = true;
        elements.list.replaceChildren();
      }
      forms.forEach((form) => {
        const input = form.querySelector(SEARCH_INPUT_SELECTOR);
        if (input) input.value = "";
      });
    };

    const elements = getSearchRegion();
    if (elements) {
      elements.clearButton.addEventListener("click", clearResults);
    }

    forms.forEach((form) => {
      const input = form.querySelector(SEARCH_INPUT_SELECTOR);
      if (!input) return;
      setupTypeahead(form, input, clearResults);

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        performAndRenderSearch(input.value.trim());
      });

      let debounceTimer;
      input.addEventListener("input", (event) => {
        const value = event.currentTarget.value.trim();
        clearTimeout(debounceTimer);
        if (!value) {
          clearResults();
          return;
        }
        debounceTimer = window.setTimeout(() => {
          performAndRenderSearch(value);
        }, 300);
      });
    });
  }

  async function performAndRenderSearch(query) {
    if (!query || query.length < 2) return;
    const form = document.querySelector(SEARCH_FORM_SELECTOR);
    if (form) form.classList.add("is-loading");
    let markup = null;
    try {
      const response = await fetch(
        `${SEARCH_RESULTS_ENDPOINT}?query=${encodeURIComponent(query)}`,
      );
      if (!response.ok) {
        throw new Error("Unable to search catalogue.");
      }
      markup = await response.text();
    } catch (error) {
      console.error(error);
      showFlash(error.message || "Search failed, please try again.", "error");
    } finally {
      if (form) form.classList.remove("is-loading");
    }
    if (markup === null) return;
    const elements = getSearchRegion();
    if (!elements) return;
    // The fragment is parsed in body context, so its <article> cards land as
    // real nodes; it also carries its own empty state (task 9.1).
    elements.list.replaceChildren(document.createRange().createContextualFragment(markup));
    elements.region.hidden = false;
  }

  // ---------------------------------------------------------------------
  // Sign-in modal (task 8.3)
  // ---------------------------------------------------------------------

  function getPrimaryNav() {
    return document.querySelector(PRIMARY_NAV_SELECTOR);
  }

  function getLoginButton() {
    const nav = getPrimaryNav();
    return nav ? nav.querySelector(LOGIN_BUTTON_SELECTOR) : null;
  }

  function getAuthOverlay() {
    const loginButton = getLoginButton();
    if (!loginButton) return null;
    // Works while the button is hidden for a signed-in user.
    return document.getElementById(loginButton.getAttribute("aria-controls"));
  }

  function getAuthElements() {
    const overlay = getAuthOverlay();
    if (!overlay) return null;
    const dialog = overlay.querySelector('[role="dialog"]');
    if (!dialog) return null;
    const form = dialog.querySelector("form");
    return {
      overlay,
      dialog,
      form,
      alert: form ? form.querySelector('[role="alert"]') : null,
      closeButton: dialog.querySelector(`[aria-label="${LOGIN_CLOSE_LABEL}"]`),
    };
  }

  function openLoginModal() {
    const elements = getAuthElements();
    if (!elements) return;
    elements.overlay.hidden = false;
    document.body.style.overflow = "hidden";
    const emailInput = elements.form?.elements?.email;
    if (emailInput) {
      // Deferred until the overlay is laid out, and skipped when focus is
      // already inside the dialog: a shopper (or a test) who has started
      // typing in another field must not have their keystrokes moved.
      window.requestAnimationFrame(() => {
        if (!elements.dialog.contains(document.activeElement)) emailInput.focus();
      });
    }
  }

  function closeLoginModal() {
    const elements = getAuthElements();
    if (!elements) return;
    elements.overlay.hidden = true;
    document.body.style.overflow = "";
    if (elements.alert) {
      elements.alert.hidden = true;
      elements.alert.textContent = "";
    }
    if (elements.form) {
      elements.form.reset();
      elements.form.classList.remove("is-loading");
    }
  }

  async function handleLoginSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const email = form.elements.email.value.trim();
    const password = form.elements.password.value;
    const alert = form.querySelector('[role="alert"]');
    if (alert) {
      alert.hidden = true;
      alert.textContent = "";
    }
    form.classList.add("is-loading");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const detail = await response.json().then((body) => body?.detail).catch(() => null);
        throw new Error(errorText(detail, "Invalid email or password"));
      }
      const data = await response.json();
      saveAuth(data);
      updateAuthUI();
      applyAuthToCheckout();
      showFlash(`Welcome back, ${data.user.full_name}!`, "success");
      closeLoginModal();
    } catch (error) {
      console.error(error);
      if (alert) {
        alert.hidden = false;
        alert.textContent = error.message || "Unable to sign in";
      }
    } finally {
      form.classList.remove("is-loading");
    }
  }

  // ---------------------------------------------------------------------
  // Account menu (task 8.3)
  // ---------------------------------------------------------------------

  function getAccountElements() {
    const navElements = getMobileNavElements();
    if (!navElements) return null;
    // Unique inside the menu: the nav's own toggle carries the same pair but
    // is a direct child of <nav>, the theme toggle carries aria-pressed, and
    // the "Log in" button carries no aria-expanded (task 8.1).
    const trigger = navElements.menu.querySelector(ACCOUNT_TRIGGER_SELECTOR);
    if (!trigger) return null;
    const panel = document.getElementById(trigger.getAttribute("aria-controls"));
    if (!panel) return null;
    return { trigger, panel };
  }

  function updateAuthUI() {
    const loginButton = getLoginButton();
    const account = getAccountElements();
    if (!loginButton && !account) return;

    if (authState) {
      if (loginButton) loginButton.hidden = true;
      if (account) {
        account.trigger.hidden = false;
        const name = account.trigger.querySelector("span");
        if (name) {
          const firstName = authState.user.full_name.split(" ")[0];
          name.textContent = `Hi, ${firstName}`;
        }
        renderAccountMenu();
        setAccountPanelOpen(false);
      }
    } else {
      if (loginButton) loginButton.hidden = false;
      if (account) {
        account.trigger.hidden = true;
        setAccountPanelOpen(false);
      }
    }
  }

  function fillAccountList(panel, label, entries, emptyText, fill) {
    const list = panel.querySelector(`ul[aria-label="${label}"]`);
    if (!list) return;
    const template = ownTemplates(list)[0] || null;
    const items = [];
    if (!entries.length) {
      const empty = document.createElement("li");
      empty.textContent = emptyText;
      items.push(empty);
    } else if (template) {
      entries.forEach((entry) => {
        const item = cloneTemplate(template);
        if (!item) return;
        fill(item, entry);
        items.push(item);
      });
    }
    // The shell stays in the list, so the next render can clone it again.
    list.replaceChildren(...(template ? [template, ...items] : items));
  }

  function renderAccountMenu() {
    const account = getAccountElements();
    if (!account || !authState) return;
    const { panel } = account;

    fillAccountList(
      panel,
      ADDRESSES_LABEL,
      authState.addresses ?? [],
      "No saved addresses yet.",
      (item, address) => {
        const label = address.label ? `${address.label}: ` : "";
        item.textContent = `${label}${address.line1}, ${address.city}, ${address.state} ${address.postal_code}`;
      },
    );

    fillAccountList(
      panel,
      PAYMENTS_LABEL,
      authState.payment_methods ?? [],
      "No saved payment methods.",
      (item, method) => {
        item.textContent = `${method.display} · Expires ${method.exp_month}/${method.exp_year}`;
      },
    );

    fillAccountList(
      panel,
      ORDERS_LABEL,
      authState.orders ?? [],
      "No orders yet.",
      (item, order) => {
        const number = item.querySelector("strong");
        if (number) number.textContent = order.order_number;
        const meta = item.querySelector("span");
        if (meta) {
          meta.textContent = ` · ${formatCurrency(order.total)} · ${order.status}`;
        }
        const links = item.querySelectorAll("a");
        if (links[0]) links[0].href = order.invoice_url;
        if (links[1]) links[1].href = order.summary_url;
      },
    );
  }

  function setAccountPanelOpen(forceState) {
    const account = getAccountElements();
    if (!account) return;
    const shouldOpen = typeof forceState === "boolean" ? forceState : account.panel.hidden;
    account.panel.hidden = !shouldOpen;
    account.trigger.setAttribute("aria-expanded", String(shouldOpen));
  }

  // ---------------------------------------------------------------------
  // Checkout autofill (task 8.3)
  // ---------------------------------------------------------------------

  function applyAuthToCheckout() {
    const form = document.querySelector(CHECKOUT_FORM_SELECTOR);
    if (!form) return;
    // The form's only direct-child <p>: the signed-in note, whose `hidden`
    // carries the signed-in state.
    const note = form.querySelector(":scope > p");
    if (!authState) {
      if (note) note.hidden = true;
      return;
    }

    const fields = form.elements;
    if (fields.email) fields.email.value = authState.user.email;
    if (fields.name) fields.name.value = authState.user.full_name;

    const primaryAddress = authState.addresses?.[0];
    if (primaryAddress && fields.address) {
      fields.address.value = `${primaryAddress.line1}${primaryAddress.line2 ? `, ${primaryAddress.line2}` : ""}\n${primaryAddress.city}, ${primaryAddress.state} ${primaryAddress.postal_code}`;
    }

    if (fields.team_size && !fields.team_size.value) {
      fields.team_size.value = "10";
    }

    if (note) {
      // The name goes into the note's only <span>, so the note keeps its
      // whole sentence.
      const nameSpan = note.querySelector("span");
      if (nameSpan) nameSpan.textContent = authState.user.full_name;
      note.hidden = false;
    }
  }

  // ---------------------------------------------------------------------
  // Mobile navigation (task 8.2)
  // ---------------------------------------------------------------------

  function getMobileNavElements() {
    const nav = getPrimaryNav();
    if (!nav) return null;
    // The nav's only direct-child button (task 8.1).
    const toggle = nav.querySelector(NAV_TOGGLE_SELECTOR);
    if (!toggle) return null;
    const menu = document.getElementById(toggle.getAttribute("aria-controls"));
    if (!menu) return null;
    return { nav, toggle, menu };
  }

  function isMobileViewport() {
    if (mobileNavMediaQuery) {
      return mobileNavMediaQuery.matches;
    }
    return window.innerWidth <= MOBILE_NAV_BREAKPOINT;
  }

  function setMobileNavOpen(nextState) {
    const elements = getMobileNavElements();
    if (!elements) return;
    const { nav, toggle, menu } = elements;
    const shouldOpen = typeof nextState === "boolean" ? nextState : !nav.classList.contains("is-open");
    nav.classList.toggle("is-open", shouldOpen);
    toggle.setAttribute("aria-expanded", String(shouldOpen));
    if (isMobileViewport()) {
      menu.hidden = !shouldOpen;
      menu.setAttribute("aria-hidden", String(!shouldOpen));
      document.body.classList.toggle("site-nav-open", shouldOpen);
    } else {
      menu.hidden = false;
      menu.removeAttribute("aria-hidden");
      document.body.classList.remove("site-nav-open");
    }
  }

  function setupMobileNav() {
    const elements = getMobileNavElements();
    if (!elements) return;
    const { nav, toggle, menu } = elements;
    const syncMenuForViewport = () => {
      if (isMobileViewport()) {
        toggle.setAttribute("aria-expanded", "false");
        if (!nav.classList.contains("is-open")) {
          menu.hidden = true;
          menu.setAttribute("aria-hidden", "true");
          document.body.classList.remove("site-nav-open");
        }
      } else {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        menu.hidden = false;
        menu.removeAttribute("aria-hidden");
        document.body.classList.remove("site-nav-open");
      }
    };

    toggle.setAttribute("aria-expanded", "false");
    nav.classList.remove("is-open");
    syncMenuForViewport();

    if (!mobileNavBound.has(nav)) {
      const handleViewportChange = () => {
        if (nav.classList.contains("is-open") && !isMobileViewport()) {
          setMobileNavOpen(false);
        }
        syncMenuForViewport();
      };
      window.addEventListener("resize", handleViewportChange);
      if (mobileNavMediaQuery) {
        mobileNavMediaQuery.addEventListener("change", handleViewportChange);
      }
      mobileNavBound.add(nav);
    }
  }

  // ---------------------------------------------------------------------
  // Document-level delegation
  // ---------------------------------------------------------------------

  function handleDocumentClick(event) {
    const navElements = getMobileNavElements();
    if (navElements) {
      const { nav, toggle, menu } = navElements;
      if (toggle.contains(event.target)) {
        event.preventDefault();
        const isOpen = !nav.classList.contains("is-open");
        setMobileNavOpen(isOpen);
        return;
      }

      if (nav.classList.contains("is-open")) {
        const withinMenu = menu.contains(event.target);
        const actionable = event.target.closest("a, button, [role='menuitem']");
        if (!withinMenu) {
          setMobileNavOpen(false);
        } else if (actionable) {
          setMobileNavOpen(false);
        }
      }
    }

    const loginButton = getLoginButton();
    if (loginButton && loginButton.contains(event.target)) {
      event.preventDefault();
      openLoginModal();
      return;
    }

    const authElements = getAuthElements();
    if (authElements) {
      const closeButton = authElements.closeButton;
      // A backdrop click is a click on the overlay itself.
      if ((closeButton && closeButton.contains(event.target)) || event.target === authElements.overlay) {
        event.preventDefault();
        closeLoginModal();
        return;
      }
    }

    const account = getAccountElements();
    if (account) {
      const logoutButton = account.panel.querySelector(`button[aria-label="${LOGOUT_LABEL}"]`);
      if (logoutButton && logoutButton.contains(event.target)) {
        event.preventDefault();
        clearAuth();
        showFlash("Signed out successfully.", "info");
        return;
      }

      if (account.trigger.contains(event.target)) {
        event.preventDefault();
        setAccountPanelOpen();
        return;
      }

      if (!account.panel.contains(event.target) && !account.trigger.contains(event.target)) {
        setAccountPanelOpen(false);
      }
    }

    const button = event.target.closest("button[data-product]");
    if (button) {
      event.preventDefault();
      addToCart(button);
    }

    if (isChatOpen) {
      const { widget, launcher, closeButton } = getChatElements();
      if (closeButton && closeButton.contains(event.target)) {
        event.preventDefault();
        toggleChat(false, { focusLauncher: true });
        return;
      }
      const onLauncher = launcher && launcher.contains(event.target);
      if (widget && !widget.contains(event.target) && !onLauncher) {
        toggleChat(false);
        return;
      }
    }
  }

  function handleDocumentKeydown(event) {
    if (event.key !== "Escape") return;
    const navElements = getMobileNavElements();
    if (!navElements) return;
    const { nav, toggle } = navElements;
    if (nav.classList.contains("is-open")) {
      setMobileNavOpen(false);
      if (toggle && typeof toggle.focus === "function") {
        toggle.focus({ preventScroll: true });
      }
    }
  }

  // ---------------------------------------------------------------------
  // Chat widget (task 8.4)
  // ---------------------------------------------------------------------

  function getChatElements() {
    // A direct child of <body>, unlike the "Log in" button, which carries the
    // same attribute pair inside the nav (task 8.1).
    const launcher = document.querySelector(CHAT_LAUNCHER_SELECTOR);
    if (!launcher) return { widget: null, launcher: null, closeButton: null };
    const widget = document.getElementById(launcher.getAttribute("aria-controls"));
    return {
      widget,
      launcher,
      closeButton: widget ? widget.querySelector(`[aria-label="${CHAT_CLOSE_LABEL}"]`) : null,
    };
  }

  function getChatLog() {
    const { widget } = getChatElements();
    return widget ? widget.querySelector(CHAT_LOG_SELECTOR) : null;
  }

  function getChatTextarea() {
    const { widget } = getChatElements();
    return widget ? widget.querySelector(CHAT_TEXTAREA_SELECTOR) : null;
  }

  function getChatForm() {
    const textarea = getChatTextarea();
    return textarea ? textarea.form : null;
  }

  function ensureChatWidgetSetup() {
    const { widget, launcher, closeButton } = getChatElements();
    if (!widget || !launcher) return;

    launcher.hidden = false;
    launcher.setAttribute("aria-expanded", String(isChatOpen));

    widget.setAttribute("aria-hidden", String(!isChatOpen));
    if (!widget.getAttribute("role")) {
      widget.setAttribute("role", "dialog");
    }
    if (widget.hidden || !isChatOpen) {
      widget.setAttribute("inert", "");
    } else {
      widget.removeAttribute("inert");
    }

    if (!chatBound.has(launcher)) {
      launcher.addEventListener("click", handleChatToggleClick);
      launcher.addEventListener("keydown", handleChatToggleKeydown);
      chatBound.add(launcher);
    }

    if (closeButton && !chatBound.has(closeButton)) {
      closeButton.addEventListener("click", handleChatCloseClick);
      chatBound.add(closeButton);
    }

    if (!chatKeydownListenerAttached) {
      document.addEventListener("keydown", handleChatKeydown);
      chatKeydownListenerAttached = true;
    }
  }

  function handleChatToggleClick(event) {
    event.preventDefault();
    toggleChat(!isChatOpen);
  }

  function handleChatToggleKeydown(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleChat(!isChatOpen);
  }

  function handleChatCloseClick(event) {
    event.preventDefault();
    toggleChat(false, { focusLauncher: true });
  }

  function handleChatKeydown(event) {
    if (event.key !== "Escape" || !isChatOpen) return;
    const { widget } = getChatElements();
    const overlay = getAuthOverlay();
    if (overlay && !overlay.hidden) {
      return;
    }
    const activeElement = document.activeElement;
    if (widget && activeElement && !widget.contains(activeElement)) {
      // Respect other overlays by ensuring focus isn't trapped elsewhere.
      const activeModal =
        typeof activeElement.closest === "function" ? activeElement.closest("[role='dialog']") : null;
      if (activeModal && activeModal !== widget) {
        return;
      }
    }
    event.preventDefault();
    toggleChat(false, { focusLauncher: true });
  }

  function toggleChat(forceOpen, options = {}) {
    const { focusLauncher = false } = options;
    const { widget, launcher } = getChatElements();
    if (!widget || !launcher) return;
    const nextState = typeof forceOpen === "boolean" ? forceOpen : !isChatOpen;
    isChatOpen = nextState;
    widget.hidden = !isChatOpen;
    launcher.hidden = isChatOpen;
    launcher.setAttribute("aria-expanded", String(isChatOpen));
    widget.setAttribute("aria-hidden", String(!isChatOpen));
    document.body.classList.toggle(CHAT_BODY_OPEN_CLASS, isChatOpen);
    if (isChatOpen) {
      widget.removeAttribute("inert");
      document.body.style.setProperty("overflow", "hidden");
      scrollChatToBottom();
      const textarea = getChatTextarea();
      if (textarea) {
        window.requestAnimationFrame(() => textarea.focus());
      }
    } else {
      widget.setAttribute("inert", "");
      document.body.style.removeProperty("overflow");
      if (focusLauncher && typeof launcher.focus === "function") {
        window.requestAnimationFrame(() => {
          launcher.focus({ preventScroll: true });
        });
      }
    }
  }

  function appendChatMessage(role, text, options = {}) {
    const log = getChatLog();
    if (!log) return null;
    // Two shells in a fixed order: the user message first, the assistant
    // message second (task 9.3). Their classes come from the template.
    const templates = ownTemplates(log);
    if (templates.length !== 2) return null;
    const message = cloneTemplate(role === "user" ? templates[0] : templates[1]);
    if (!message) return null;
    if (options.loading) {
      message.setAttribute("aria-busy", "true");
    } else {
      message.textContent = text;
    }
    log.appendChild(message);
    scrollChatToBottom();
    return message;
  }

  function scrollChatToBottom() {
    const log = getChatLog();
    if (!log) return;
    log.scrollTop = log.scrollHeight;
  }

  async function handleChatSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const textarea = form.querySelector(CHAT_TEXTAREA_SELECTOR);
    if (!textarea) return;
    const question = textarea.value.trim();
    if (!question) return;

    textarea.value = "";
    appendChatMessage("user", question);
    const pending = appendChatMessage("assistant", "", { loading: true });

    try {
      const response = await fetch("/api/ai/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode: "summary" }),
      });
      if (!response.ok) {
        const detail = await response.json().then((body) => body?.detail).catch(() => null);
        throw new Error(errorText(detail, "Assistant unavailable"));
      }
      const data = await response.json();
      const answer =
        data?.answer?.summary ||
        data?.answer?.answer ||
        (Array.isArray(data?.answer?.highlights) ? data.answer.highlights.join("\n") : null) ||
        "I'm not sure how to help with that right now.";
      if (pending) {
        pending.removeAttribute("aria-busy");
        pending.textContent = answer;
      }
      chatHistory.push({ role: "user", content: question }, { role: "assistant", content: answer });
    } catch (error) {
      console.error(error);
      if (pending) {
        pending.removeAttribute("aria-busy");
        pending.textContent = error.message || "I ran into an issue answering that.";
      }
    }
  }

  function handleChatTextareaKeydown(event) {
    if (event.key !== "Enter") return;
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.shiftKey) return;
    event.preventDefault();
    const form = event.currentTarget.closest("form");
    if (form && typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else if (form) {
      form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    }
  }

  // ---------------------------------------------------------------------
  // Theme toggle (task 8.2). The sun/moon swap lives in the stylesheet.
  // ---------------------------------------------------------------------

  function getThemeToggle() {
    const nav = getPrimaryNav();
    return nav ? nav.querySelector("button[aria-pressed]") : null;
  }

  function initializeTheme() {
    const saved = getStoredTheme();
    const prefersDark = window.matchMedia
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
    const startingTheme = saved || (prefersDark ? "dark" : "light");
    applyTheme(startingTheme, { persist: !!saved });

    const toggle = getThemeToggle();
    if (toggle && !themeBound.has(toggle)) {
      toggle.addEventListener("click", () => {
        const nextTheme = currentTheme === "dark" ? "light" : "dark";
        applyTheme(nextTheme, { persist: true });
      });
      themeBound.add(toggle);
    }

    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const mqHandler = (event) => {
        if (getStoredTheme()) return;
        applyTheme(event.matches ? "dark" : "light");
      };
      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", mqHandler);
      } else if (typeof mq.addListener === "function") {
        mq.addListener(mqHandler);
      }
    }
  }

  function applyTheme(theme, options = {}) {
    const { persist = false } = options;
    const resolved = theme === "dark" ? "dark" : "light";
    currentTheme = resolved;
    document.body.classList.toggle(THEME_DARK_CLASS, resolved === "dark");
    updateThemeToggleUI(resolved);
    if (persist) {
      storeTheme(resolved);
    }
  }

  function updateThemeToggleUI(theme) {
    const toggle = getThemeToggle();
    if (!toggle) return;
    const isDark = theme === "dark";
    toggle.setAttribute("aria-pressed", String(isDark));
    toggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
    // The button's only <span> (task 8.1).
    const label = toggle.querySelector("span");
    if (label) {
      label.textContent = isDark ? "Light mode" : "Dark mode";
    }
  }

  function getStoredTheme() {
    try {
      const value = localStorage.getItem(THEME_STORAGE_KEY);
      if (value === "dark" || value === "light") {
        return value;
      }
      return null;
    } catch {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore persistence failures */
    }
  }

  // ---------------------------------------------------------------------
  // Product filters (task 8.4)
  // ---------------------------------------------------------------------

  function initializeFilters() {
    const priceInput = document.querySelector('input[name="price_min"]');
    const form = priceInput ? priceInput.form : null;
    if (!form) return;
    setupPriceSlider(form);
    const selectableChips = form.querySelectorAll(".chip--selectable");
    selectableChips.forEach((chip) => {
      const input = chip.querySelector('input[type="checkbox"]');
      if (!input) return;
      const updateChipState = () => {
        chip.classList.toggle("chip--active", input.checked);
      };
      input.addEventListener("change", updateChipState);
      updateChipState();
    });
  }

  function setupPriceSlider(form) {
    const minSlider = form.querySelector(MIN_PRICE_SLIDER_SELECTOR);
    const maxSlider = form.querySelector(MAX_PRICE_SLIDER_SELECTOR);
    const minInput = form.elements.price_min;
    const maxInput = form.elements.price_max;
    if (!minSlider || !maxSlider || !minInput || !maxInput) {
      return;
    }

    // Each output points at its slider with `for`.
    let minOutput = null;
    let maxOutput = null;
    form.querySelectorAll("output[for]").forEach((output) => {
      const slider = document.getElementById(output.htmlFor);
      if (slider === minSlider) {
        minOutput = output;
      } else if (slider === maxSlider) {
        maxOutput = output;
      }
    });
    if (!minOutput || !maxOutput) {
      return;
    }

    // The reset defaults are the sliders' own bounds.
    const defaults = {
      min: Number(minSlider.min || 0),
      max: Number(maxSlider.max || 0),
    };

    const syncOutputs = () => {
      const minValue = Math.min(Number(minSlider.value), Number(maxSlider.value));
      const maxValue = Math.max(Number(maxSlider.value), minValue);
      minSlider.value = String(minValue);
      maxSlider.value = String(maxValue);
      // Prices are shown and submitted in cents, so the lowest price stays in range.
      minOutput.textContent = minValue.toFixed(2);
      maxOutput.textContent = maxValue.toFixed(2);
      minInput.value = minValue.toFixed(2);
      maxInput.value = maxValue.toFixed(2);
    };

    minSlider.addEventListener("input", syncOutputs);
    maxSlider.addEventListener("input", syncOutputs);

    form.addEventListener("reset", () => {
      window.requestAnimationFrame(() => {
        minSlider.value = String(defaults.min);
        maxSlider.value = String(defaults.max);
        syncOutputs();
      });
    });

    syncOutputs();
  }

  // ---------------------------------------------------------------------
  // Search typeahead (tasks 8.4 and 9.3)
  // ---------------------------------------------------------------------

  function setupTypeahead(form, input, clearResults) {
    // The anchor is the field's own <label>, which holds the dropdown shell.
    const anchor = input.closest("label");
    if (!anchor) return;
    const anchorTemplates = ownTemplates(anchor);
    if (anchorTemplates.length !== 1) return;
    const dropdown = cloneTemplate(anchorTemplates[0]);
    if (!dropdown) return;

    const list = dropdown.querySelector('[role="listbox"]');
    const emptyState = dropdown.querySelector(".search-suggest__empty");
    if (!list || !emptyState) return;
    const optionTemplates = ownTemplates(list);
    if (optionTemplates.length !== 1) return;
    const optionTemplate = optionTemplates[0];
    anchor.appendChild(dropdown);

    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", list.id);

    let items = [];
    let activeIndex = -1;
    let debounceTimer;

    const options = () => list.querySelectorAll(OPTION_SELECTOR);

    const hide = () => {
      dropdown.hidden = true;
      input.setAttribute("aria-expanded", "false");
      items = [];
      activeIndex = -1;
      list.replaceChildren(optionTemplate);
      emptyState.hidden = true;
    };

    const setActive = (index) => {
      if (!items.length) {
        activeIndex = -1;
        return;
      }
      if (index < 0) {
        activeIndex = items.length - 1;
      } else if (index >= items.length) {
        activeIndex = 0;
      } else {
        activeIndex = index;
      }
      options().forEach((option, optionIndex) => {
        const isActive = optionIndex === activeIndex;
        option.classList.toggle("is-active", isActive);
        option.setAttribute("aria-selected", String(isActive));
      });
    };

    const renderSuggestions = (query, results) => {
      items = results;
      if (!results.length) {
        list.replaceChildren(optionTemplate);
        emptyState.hidden = false;
        dropdown.hidden = false;
        input.setAttribute("aria-expanded", "true");
        activeIndex = -1;
        return;
      }

      emptyState.hidden = true;
      const rendered = [];
      results.forEach((item) => {
        const option = cloneTemplate(optionTemplate);
        if (!option) return;
        const label = option.querySelector(".search-suggest__label");
        const category = option.querySelector(".search-suggest__category");
        if (label) fillHighlighted(label, item.name, query);
        if (category) category.textContent = item.category || "General";
        rendered.push(option);
      });
      // The option shell stays first, so the next render can clone it again.
      list.replaceChildren(optionTemplate, ...rendered);
      dropdown.hidden = false;
      input.setAttribute("aria-expanded", "true");
      // No option is active until the shopper moves into the list, so Enter
      // submits the typed search (WEB-004 AC-3) instead of opening whichever
      // suggestion happened to arrive first.
      activeIndex = -1;
      rendered.forEach((option) => option.setAttribute("aria-selected", "false"));
    };

    const fetchSuggestions = async (query) => {
      if (!query || query.length < 2) {
        hide();
        return;
      }
      try {
        const response = await fetch(`${SEARCH_SUGGEST_ENDPOINT}?query=${encodeURIComponent(query)}`);
        if (!response.ok) {
          throw new Error("Unable to retrieve suggestions");
        }
        const data = await response.json();
        const results = Array.isArray(data?.results) ? data.results : [];
        renderSuggestions(query, results);
      } catch (error) {
        console.error(error);
        hide();
      }
    };

    const selectSuggestion = (index) => {
      const item = items[index];
      if (!item) return;
      window.location.href = `/products/${item.id}`;
    };

    input.addEventListener("input", (event) => {
      const value = event.currentTarget.value.trim();
      clearTimeout(debounceTimer);
      if (!value) {
        hide();
        if (typeof clearResults === "function") {
          clearResults();
        }
        return;
      }
      debounceTimer = window.setTimeout(() => {
        fetchSuggestions(value);
      }, 300);
    });

    input.addEventListener("keydown", (event) => {
      if (dropdown.hidden) return;
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          setActive(activeIndex + 1);
          break;
        case "ArrowUp":
          event.preventDefault();
          setActive(activeIndex - 1);
          break;
        case "Enter":
          if (activeIndex >= 0) {
            event.preventDefault();
            selectSuggestion(activeIndex);
            hide();
          }
          break;
        case "Escape":
          hide();
          break;
        default:
          break;
      }
    });

    list.addEventListener("mousedown", (event) => {
      const target = event.target.closest(OPTION_SELECTOR);
      if (!target) return;
      event.preventDefault();
      // An option's index is its position among the listbox's options.
      const index = Array.prototype.indexOf.call(options(), target);
      if (index >= 0) {
        selectSuggestion(index);
        hide();
      }
    });

    document.addEventListener("click", (event) => {
      if (!form.contains(event.target)) {
        hide();
      }
    });

    form.addEventListener("submit", hide);
  }

  function fillHighlighted(element, text, query) {
    const value = String(text ?? "");
    const pattern = String(query ?? "").trim();
    if (!pattern) {
      element.textContent = value;
      return;
    }
    const regex = new RegExp(escapeRegExp(pattern), "ig");
    const parts = [];
    let lastIndex = 0;
    let match = regex.exec(value);
    while (match) {
      if (match.index > lastIndex) {
        parts.push(document.createTextNode(value.slice(lastIndex, match.index)));
      }
      const mark = document.createElement("mark");
      mark.textContent = match[0];
      parts.push(mark);
      lastIndex = match.index + match[0].length;
      if (match[0].length === 0) {
        regex.lastIndex += 1;
      }
      match = regex.exec(value);
    }
    if (lastIndex < value.length) {
      parts.push(document.createTextNode(value.slice(lastIndex)));
    }
    element.replaceChildren(...parts);
  }

  // ---------------------------------------------------------------------
  // Inspiration prompts
  // ---------------------------------------------------------------------

  function attachInspirationPrompts() {
    const buttons = document.querySelectorAll("[data-chat-prompt]");
    if (!buttons.length) return;
    buttons.forEach((button) => {
      if (chatPromptBound.has(button)) return;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const prompt = button.dataset.chatPrompt;
        if (!prompt) return;
        ensureChatOpenWithPrompt(prompt);
      });
      chatPromptBound.add(button);
    });
  }

  function ensureChatOpenWithPrompt(prompt) {
    toggleChat(true);
    const textarea = getChatTextarea();
    if (!textarea) return;
    textarea.value = prompt;
    textarea.focus({ preventScroll: false });
  }

  // ---------------------------------------------------------------------
  // Start-up
  // ---------------------------------------------------------------------

  async function init() {
    authState = loadAuth();
    updateAuthUI();
    applyAuthToCheckout();
    initializeTheme();
    initializeFilters();
    setupMobileNav();

    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("keydown", handleDocumentKeydown);
    const authElements = getAuthElements();
    if (authElements && authElements.form) {
      authElements.form.addEventListener("submit", handleLoginSubmit);
    }

    attachSearch();
    await fetchCartState();

    ensureChatWidgetSetup();

    const chatForm = getChatForm();
    if (chatForm) {
      chatForm.addEventListener("submit", handleChatSubmit);
      const chatTextarea = getChatTextarea();
      if (chatTextarea && !chatBound.has(chatTextarea)) {
        chatTextarea.addEventListener("keydown", handleChatTextareaKeydown);
        chatBound.add(chatTextarea);
      }
    }

    attachInspirationPrompts();
  }

  init();
})();

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
