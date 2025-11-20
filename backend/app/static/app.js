(() => {
  const SESSION_COOKIE = "session_id";
  const CART_ENDPOINT = "/api/cart";
  const CART_ITEMS_ENDPOINT = "/api/cart/items";
  const CART_BADGE_SELECTOR = "[data-cart-count]";
  const FLASH_ID = "flash-message";
  const SESSION_COOKIE_DAYS = 30;
  const SEARCH_ENDPOINT = "/api/search/";
  const SEARCH_RESULTS_WRAPPER_SELECTOR = "[data-search-results-wrapper]";
  const SEARCH_RESULTS_SELECTOR = "[data-search-results]";
  const SEARCH_EMPTY_SELECTOR = "[data-search-empty]";
  const SEARCH_CLEAR_SELECTOR = "[data-search-clear]";
  const SEARCH_SUGGEST_ENDPOINT = "/api/search/suggest";
  const AUTH_STORAGE_KEY = "flowline_auth_state";
  const CHAT_WIDGET_SELECTOR = "[data-chat-widget]";
  const CHAT_TOGGLE_SELECTOR = "[data-chat-toggle]";
  const CHAT_CLOSE_SELECTOR = "[data-chat-close]";
  const CHAT_FORM_SELECTOR = "[data-chat-form]";
  const CHAT_MESSAGES_SELECTOR = "[data-chat-messages]";
  const CHAT_BODY_OPEN_CLASS = "has-chat-open";
  const THEME_STORAGE_KEY = "flowline_theme";
  const THEME_TOGGLE_SELECTOR = "[data-theme-toggle]";
  const THEME_LABEL_SELECTOR = "[data-theme-label]";
  const THEME_ICON_SUN = "[data-icon-sun]";
  const THEME_ICON_MOON = "[data-icon-moon]";
  const THEME_DARK_CLASS = "theme-dark";
  const MOBILE_NAV_BREAKPOINT = 600;
  const mobileNavMediaQuery =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT}px)`)
      : null;

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

  function showFlash(message, variant = "info") {
    const flash = document.getElementById(FLASH_ID);
    if (!flash) return;
    flash.textContent = message;
    flash.className = `flash is-visible ${variant}`;
    clearTimeout(flashTimer);
    flashTimer = window.setTimeout(() => {
      flash.className = "flash";
      flash.textContent = "";
    }, 3500);
  }

  function updateCartBadge(state) {
    const badge = document.querySelector(CART_BADGE_SELECTOR);
    if (!badge) return;
    const items = Array.isArray(state?.items) ? state.items : [];
    const quantity = items.reduce(
      (total, item) => total + Number(item?.quantity ?? 0),
      0,
    );
    if (quantity > 0) {
      badge.textContent = quantity;
      badge.classList.add("is-visible");
    } else {
      badge.textContent = "";
      badge.classList.remove("is-visible");
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
    const quantityAttr = Number(button.dataset.quantity);
    const quantity = Number.isFinite(quantityAttr) && quantityAttr > 0 ? quantityAttr : 1;
    const productName =
      button.dataset.productName ||
      button.closest("[data-test='product-card']")?.querySelector(".product-card__title a")?.textContent ||
      "Unknown product";

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
        throw new Error(detail || "Unable to add item to cart.");
      }

      const cartState = await response.json();
      updateCartBadge(cartState);
      showFlash("Item added to cart.", "success");
      window.analyticsTrack("add_to_cart", {
        product_id: productId,
        product_name: productName,
        quantity,
        source: button.closest("[data-test='product-card']") ? "product_card" : "cta",
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

  function renderProductCards(products) {
    return products
      .map(
        (product) => `
      <article class="product-card" data-test="product-card">
        <div class="product-card__media">
          <picture>
            <source srcset="${product.image_url}" type="image/jpeg" />
            <img src="${product.image_url}" alt="${product.name} product photo" loading="lazy" />
          </picture>
          <button class="card-action" data-event="add_to_cart" data-product="${product.id}" data-product-name="${product.name}"
            aria-label="Add ${product.name} to cart">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
              stroke-linecap="round" stroke-linejoin="round">
              <circle cx="9" cy="21" r="1"></circle>
              <circle cx="20" cy="21" r="1"></circle>
              <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61H19a2 2 0 0 0 2-1.61L23 6H6"></path>
            </svg>
          </button>
        </div>
        <div class="product-card__body">
          ${product.category
            ? `<span class="category-badge" data-category="${String(product.category).toLowerCase()}">${product.category}</span>`
            : ""
          }
          <h3 class="product-card__title"><a href="/products/${product.id}">${product.name}</a></h3>
          ${product.description ? `<p class="product-card__description">${product.description}</p>` : ""
          }
        </div>
        <div class="product-card__footer">
          <span class="product-card__price">${formatCurrency(product.price)}</span>
          <div class="product-card__cta">
            <button class="button button--primary" data-event="add_to_cart" data-product="${product.id}" data-product-name="${product.name}"
              aria-label="Add ${product.name} to cart">Add to cart</button>
            <a class="button button--ghost" href="/products/${product.id}" aria-label="View ${product.name}">View ${product.name}</a>
          </div>
        </div>
      </article>
    `,
      )
      .join("");
  }

  function getSearchElements() {
    const wrapper = document.querySelector(SEARCH_RESULTS_WRAPPER_SELECTOR);
    if (!wrapper) return null;
    const list = wrapper.querySelector(SEARCH_RESULTS_SELECTOR);
    const empty = wrapper.querySelector(SEARCH_EMPTY_SELECTOR);
    if (!list || !empty) return null;
    return { wrapper, list, empty };
  }

  function attachSearch() {
    const forms = document.querySelectorAll("[data-search-form]");
    if (!forms.length) return;

    const clearResults = () => {
      const elements = getSearchElements();
      if (!elements) return;
      elements.wrapper.hidden = true;
      elements.list.innerHTML = "";
      elements.empty.hidden = true;
      forms.forEach((form) => {
        const input = form.querySelector("[data-search-input]");
        if (input) input.value = "";
      });
    };

    const clearButtons = document.querySelectorAll(SEARCH_CLEAR_SELECTOR);
    clearButtons.forEach((button) => button.addEventListener("click", clearResults));

    forms.forEach((form) => {
      const input = form.querySelector("[data-search-input]");
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

  async function performSearch(query) {
    if (!query || query.length < 2) {
      return { results: [] };
    }
    try {
      const response = await fetch(`${SEARCH_ENDPOINT}?query=${encodeURIComponent(query)}`);
      if (!response.ok) {
        throw new Error("Unable to search catalogue.");
      }
      return await response.json();
    } catch (error) {
      console.error(error);
      showFlash(error.message || "Search failed, please try again.", "error");
      return { results: [] };
    }
  }

  async function performAndRenderSearch(query) {
    if (!query || query.length < 2) return;
    const form = document.querySelector("[data-search-form]");
    if (form) form.classList.add("is-loading");
    const data = await performSearch(query);
    if (form) form.classList.remove("is-loading");
    const elements = getSearchElements();
    if (!elements) return;
    const products = data?.results ?? [];
    elements.wrapper.hidden = false;
    if (products.length) {
      elements.list.innerHTML = renderProductCards(products);
      elements.empty.hidden = true;
    } else {
      elements.list.innerHTML = "";
      elements.empty.hidden = false;
    }
  }

  function openLoginModal() {
    const modal = document.querySelector("[data-auth-modal]");
    if (!modal) return;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    const emailInput = modal.querySelector("#auth-email");
    if (emailInput) {
      window.requestAnimationFrame(() => emailInput.focus());
    }
  }

  function closeLoginModal() {
    const modal = document.querySelector("[data-auth-modal]");
    if (!modal) return;
    modal.hidden = true;
    document.body.style.overflow = "";
    const alert = modal.querySelector("[data-auth-alert]");
    if (alert) {
      alert.hidden = true;
      alert.textContent = "";
    }
    const form = modal.querySelector("[data-auth-form]");
    if (form) {
      form.reset();
      form.classList.remove("is-loading");
    }
  }

  async function handleLoginSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const email = form.email.value.trim();
    const password = form.password.value;
    const alert = form.querySelector("[data-auth-alert]");
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
        throw new Error(detail || "Invalid email or password");
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

  function updateAuthUI() {
    const region = document.querySelector("[data-auth-region]");
    if (!region) return;
    const loginBtn = region.querySelector("[data-auth-login]");
    const menu = region.querySelector("[data-auth-menu]");
    const triggerName = region.querySelector("[data-auth-user-name]");
    const panel = region.querySelector("[data-auth-menu-panel]");

    if (authState) {
      if (loginBtn) loginBtn.hidden = true;
      if (menu) menu.hidden = false;
      if (triggerName) {
        const firstName = authState.user.full_name.split(" ")[0];
        triggerName.textContent = `Hi, ${firstName}`;
      }
      renderAccountMenu();
      if (panel) panel.hidden = true;
    } else {
      if (loginBtn) loginBtn.hidden = false;
      if (menu) menu.hidden = true;
    }
  }

  function renderAccountMenu() {
    const region = document.querySelector("[data-auth-region]");
    if (!region || !authState) return;
    const addressesList = region.querySelector("[data-auth-addresses]");
    const paymentsList = region.querySelector("[data-auth-payments]");
    const ordersList = region.querySelector("[data-auth-orders]");

    if (addressesList) {
      if (authState.addresses?.length) {
        addressesList.innerHTML = authState.addresses
          .map((addr) => {
            const label = addr.label ? `${addr.label}: ` : "";
            return `<li>${label}${addr.line1}, ${addr.city}, ${addr.state} ${addr.postal_code}</li>`;
          })
          .join("");
      } else {
        addressesList.innerHTML = "<li>No saved addresses yet.</li>";
      }
    }

    if (paymentsList) {
      if (authState.payment_methods?.length) {
        paymentsList.innerHTML = authState.payment_methods
          .map((pm) => `<li>${pm.display} &middot; Expires ${pm.exp_month}/${pm.exp_year}</li>`)
          .join("");
      } else {
        paymentsList.innerHTML = "<li>No saved payment methods.</li>";
      }
    }

    if (ordersList) {
      if (authState.orders?.length) {
        ordersList.innerHTML = authState.orders
          .map(
            (order) => `<li>
              <strong>${order.order_number}</strong> · ${formatCurrency(order.total)} · ${order.status}
              <div class="account-dropdown__links">
                <a href="${order.invoice_url}" target="_blank" rel="noopener">Invoice</a>
                <a href="${order.summary_url}" target="_blank" rel="noopener">Summary</a>
              </div>
            </li>`,
          )
          .join("");
      } else {
        ordersList.innerHTML = "<li>No orders yet.</li>";
      }
    }
  }

  function applyAuthToCheckout() {
    const form = document.querySelector(".checkout-form");
    const note = document.querySelector("[data-auth-note]");
    if (!form) return;
    if (!authState) {
      if (note) note.hidden = true;
      return;
    }

    const emailInput = form.querySelector("#checkout-email");
    const nameInput = form.querySelector("#checkout-name");
    const addressInput = form.querySelector("#checkout-address");
    const teamSize = form.querySelector("#checkout-team-size");

    if (emailInput) emailInput.value = authState.user.email;
    if (nameInput) nameInput.value = authState.user.full_name;

    const primaryAddress = authState.addresses?.[0];
    if (primaryAddress && addressInput) {
      addressInput.value = `${primaryAddress.line1}${primaryAddress.line2 ? `, ${primaryAddress.line2}` : ""}\n${primaryAddress.city}, ${primaryAddress.state} ${primaryAddress.postal_code}`;
    }

    if (teamSize && !teamSize.value) {
      teamSize.value = "10";
    }

    if (note) {
      const nameSpan = note.querySelector("[data-auth-note-name]");
      if (nameSpan) nameSpan.textContent = authState.user.full_name;
      note.hidden = false;
    }
  }

  function toggleAccountPanel(forceState) {
    const panel = document.querySelector("[data-auth-menu-panel]");
    if (!panel) return;
    const shouldOpen = typeof forceState === "boolean" ? forceState : panel.hidden;
    panel.hidden = !shouldOpen;
  }

  function getMobileNavElements() {
    const nav = document.querySelector(".site-nav");
    if (!nav) return null;
    const toggle = nav.querySelector("[data-nav-toggle]");
    const menu = nav.querySelector("[data-nav-menu]");
    if (!toggle || !menu) return null;
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

    if (!nav.dataset.mobileNavBound) {
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
      nav.dataset.mobileNavBound = "true";
    }
  }

  function handleDocumentClick(event) {
    const navElements = getMobileNavElements();
    if (navElements) {
      const { nav, toggle, menu } = navElements;
      const toggleButton = event.target.closest("[data-nav-toggle]");
      if (toggleButton) {
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

    const loginBtn = event.target.closest("[data-auth-login]");
    if (loginBtn) {
      event.preventDefault();
      openLoginModal();
      return;
    }

    const closeBtn = event.target.closest("[data-auth-close]");
    if (closeBtn || event.target.matches("[data-auth-modal]")) {
      event.preventDefault();
      closeLoginModal();
      return;
    }

    const logoutBtn = event.target.closest("[data-auth-logout]");
    if (logoutBtn) {
      event.preventDefault();
      clearAuth();
      showFlash("Signed out successfully.", "info");
      return;
    }

    const toggleBtn = event.target.closest("[data-auth-menu-toggle]");
    if (toggleBtn) {
      event.preventDefault();
      toggleAccountPanel();
      return;
    }

    if (!event.target.closest("[data-auth-region]")) {
      toggleAccountPanel(false);
    }

    const button = event.target.closest("button[data-product]");
    if (button) {
      event.preventDefault();
      addToCart(button);
    }

    if (isChatOpen) {
      const { widget } = getChatElements();
      const pushButton = event.target.closest(CHAT_TOGGLE_SELECTOR);
      const closeButton = event.target.closest(CHAT_CLOSE_SELECTOR);
      if (closeButton) {
        event.preventDefault();
        toggleChat(false, { focusLauncher: true });
        return;
      }
      if (widget && !widget.contains(event.target) && !pushButton) {
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

  function getChatElements() {
    const widget = document.querySelector(CHAT_WIDGET_SELECTOR);
    const launcher = document.querySelector(CHAT_TOGGLE_SELECTOR);
    const closeButton = widget?.querySelector(CHAT_CLOSE_SELECTOR);
    return { widget, launcher, closeButton };
  }

  function ensureChatWidgetSetup() {
    const { widget, launcher, closeButton } = getChatElements();
    if (!widget || !launcher) return;

    if (!widget.id) {
      widget.id = "chat-widget";
    }

    launcher.hidden = false;
    launcher.setAttribute("aria-controls", widget.id);
    launcher.setAttribute("aria-expanded", String(isChatOpen));
    launcher.setAttribute("aria-haspopup", "dialog");

    widget.setAttribute("aria-hidden", String(!isChatOpen));
    if (!widget.getAttribute("role")) {
      widget.setAttribute("role", "dialog");
    }
    if (widget.hidden || !isChatOpen) {
      widget.setAttribute("inert", "");
    } else {
      widget.removeAttribute("inert");
    }

    if (!launcher.dataset.chatBound) {
      launcher.addEventListener("click", handleChatToggleClick);
      launcher.addEventListener("keydown", handleChatToggleKeydown);
      launcher.dataset.chatBound = "true";
    }

    if (closeButton && !closeButton.dataset.chatBound) {
      closeButton.addEventListener("click", handleChatCloseClick);
      closeButton.dataset.chatBound = "true";
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
    const authModal = document.querySelector("[data-auth-modal]");
    if (authModal && !authModal.hidden) {
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

  async function init() {
    authState = loadAuth();
    updateAuthUI();
    applyAuthToCheckout();
    initializeTheme();
    initializeFilters();
    setupMobileNav();

    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("keydown", handleDocumentKeydown);
    const loginForm = document.querySelector("[data-auth-form]");
    if (loginForm) {
      loginForm.addEventListener("submit", handleLoginSubmit);
    }

    attachSearch();
    await fetchCartState();

    ensureChatWidgetSetup();

    const chatForm = document.querySelector(CHAT_FORM_SELECTOR);
    if (chatForm) {
      chatForm.addEventListener("submit", handleChatSubmit);
      const chatTextarea = chatForm.querySelector("textarea[name='question']");
      if (chatTextarea && !chatTextarea.dataset.chatBound) {
        chatTextarea.addEventListener("keydown", handleChatTextareaKeydown);
        chatTextarea.dataset.chatBound = "true";
      }
    }

    attachInspirationPrompts();
  }

  init();

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
      const textarea = widget.querySelector("textarea");
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
    const container = document.querySelector(CHAT_MESSAGES_SELECTOR);
    if (!container) return;
    const wrapper = document.createElement("div");
    wrapper.className = `chat-message chat-message--${role}`;
    if (options.loading) {
      wrapper.classList.add("chat-message--loading");
    } else {
      wrapper.textContent = text;
    }
    container.appendChild(wrapper);
    scrollChatToBottom();
    return wrapper;
  }

  function scrollChatToBottom() {
    const container = document.querySelector(CHAT_MESSAGES_SELECTOR);
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }

  async function handleChatSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const textarea = form.querySelector("textarea[name='question']");
    if (!textarea) return;
    const question = textarea.value.trim();
    if (!question) return;

    textarea.value = "";
    const userMessageEl = appendChatMessage("user", question);
    const loadingEl = appendChatMessage("assistant", "", { loading: true });

    try {
      const response = await fetch("/api/ai/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode: "summary" }),
      });
      if (!response.ok) {
        const detail = await response.json().then((body) => body?.detail).catch(() => null);
        throw new Error(detail || "Assistant unavailable");
      }
      const data = await response.json();
      const answer =
        data?.answer?.summary ||
        data?.answer?.answer ||
        (Array.isArray(data?.answer?.highlights) ? data.answer.highlights.join("\n") : null) ||
        "I'm not sure how to help with that right now.";
      loadingEl.classList.remove("chat-message--loading");
      loadingEl.textContent = answer;
      chatHistory.push({ role: "user", content: question }, { role: "assistant", content: answer });
    } catch (error) {
      console.error(error);
      loadingEl.classList.remove("chat-message--loading");
      loadingEl.classList.add("chat-message--assistant");
      loadingEl.textContent = error.message || "I ran into an issue answering that.";
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

  function initializeTheme() {
    const saved = getStoredTheme();
    const prefersDark = window.matchMedia
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
    const startingTheme = saved || (prefersDark ? "dark" : "light");
    applyTheme(startingTheme, { persist: !!saved });

    const toggle = document.querySelector(THEME_TOGGLE_SELECTOR);
    if (toggle && !toggle.dataset.themeBound) {
      toggle.addEventListener("click", () => {
        const nextTheme = currentTheme === "dark" ? "light" : "dark";
        applyTheme(nextTheme, { persist: true });
      });
      toggle.dataset.themeBound = "true";
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
    const toggle = document.querySelector(THEME_TOGGLE_SELECTOR);
    if (!toggle) return;
    const label = toggle.querySelector(THEME_LABEL_SELECTOR);
    const sunIcon = toggle.querySelector(THEME_ICON_SUN);
    const moonIcon = toggle.querySelector(THEME_ICON_MOON);
    const isDark = theme === "dark";
    toggle.setAttribute("aria-pressed", String(isDark));
    toggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
    if (label) {
      label.textContent = isDark ? "Light mode" : "Dark mode";
    }
    if (sunIcon) {
      if (isDark) {
        sunIcon.setAttribute("hidden", "");
      } else {
        sunIcon.removeAttribute("hidden");
      }
    }
    if (moonIcon) {
      if (isDark) {
        moonIcon.removeAttribute("hidden");
      } else {
        moonIcon.setAttribute("hidden", "");
      }
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

  function initializeFilters() {
    const form = document.querySelector("[data-filter-form]");
    if (!form) return;
    const priceWrapper = form.querySelector("[data-price-slider]");
    if (priceWrapper) {
      setupPriceSlider(priceWrapper, form);
    }
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

  function setupPriceSlider(wrapper, form) {
    const minSlider = wrapper.querySelector('[data-price-slider="min"]');
    const maxSlider = wrapper.querySelector('[data-price-slider="max"]');
    const minOutput = wrapper.querySelector('[data-price-output="min"]');
    const maxOutput = wrapper.querySelector('[data-price-output="max"]');
    const minInput = wrapper.querySelector('input[name="price_min"]');
    const maxInput = wrapper.querySelector('input[name="price_max"]');
    if (!minSlider || !maxSlider || !minOutput || !maxOutput || !minInput || !maxInput) {
      return;
    }

    const defaults = {
      min: Number(wrapper.dataset.priceMinDefault || minSlider.min || 0),
      max: Number(wrapper.dataset.priceMaxDefault || maxSlider.max || 0),
    };

    const syncOutputs = () => {
      const minValue = Math.min(Number(minSlider.value), Number(maxSlider.value));
      const maxValue = Math.max(Number(maxSlider.value), minValue);
      minSlider.value = String(minValue);
      maxSlider.value = String(maxValue);
      minOutput.textContent = Math.round(minValue);
      maxOutput.textContent = Math.round(maxValue);
      minInput.value = String(minValue);
      maxInput.value = String(maxValue);
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

  function setupTypeahead(form, input, clearResults) {
    const field = form.querySelector(".form-field");
    if (!field) return;

    const dropdown = document.createElement("div");
    dropdown.className = "search-suggest";
    dropdown.hidden = true;
    const list = document.createElement("ul");
    list.className = "search-suggest__list";
    list.setAttribute("role", "listbox");
    const listboxId = uniqueId("suggestions");
    list.id = listboxId;
    const emptyState = document.createElement("div");
    emptyState.className = "search-suggest__empty";
    emptyState.textContent = "No results";
    emptyState.hidden = true;
    dropdown.append(list, emptyState);
    field.appendChild(dropdown);

    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", listboxId);

    let items = [];
    let activeIndex = -1;
    let debounceTimer;

    const hide = () => {
      dropdown.hidden = true;
      input.setAttribute("aria-expanded", "false");
      items = [];
      activeIndex = -1;
      list.innerHTML = "";
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
      const options = list.querySelectorAll(".search-suggest__item");
      options.forEach((option, optionIndex) => {
        const isActive = optionIndex === activeIndex;
        option.classList.toggle("is-active", isActive);
        option.setAttribute("aria-selected", String(isActive));
      });
    };

    const renderSuggestions = (query, results) => {
      items = results;
      list.innerHTML = "";
      if (!results.length) {
        emptyState.hidden = false;
        dropdown.hidden = false;
        input.setAttribute("aria-expanded", "true");
        activeIndex = -1;
        return;
      }

      emptyState.hidden = true;
      const fragment = document.createDocumentFragment();
      results.forEach((item, index) => {
        const li = document.createElement("li");
        li.className = "search-suggest__item";
        li.setAttribute("role", "option");
        li.dataset.index = String(index);
        li.innerHTML = `
          <span class="search-suggest__label">${highlightMatch(item.name, query)}</span>
          <span class="search-suggest__category">${escapeHtml(item.category || "General")}</span>
        `;
        fragment.appendChild(li);
      });
      list.appendChild(fragment);
      dropdown.hidden = false;
      input.setAttribute("aria-expanded", "true");
      setActive(0);
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
      const target = event.target.closest(".search-suggest__item");
      if (!target) return;
      event.preventDefault();
      const index = Number(target.dataset.index);
      if (Number.isFinite(index)) {
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

  function attachInspirationPrompts() {
    const buttons = document.querySelectorAll("[data-chat-prompt]");
    if (!buttons.length) return;
    buttons.forEach((button) => {
      if (button.dataset.chatPromptBound) return;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const prompt = button.dataset.chatPrompt;
        if (!prompt) return;
        ensureChatOpenWithPrompt(prompt);
      });
      button.dataset.chatPromptBound = "true";
    });
  }

  function ensureChatOpenWithPrompt(prompt) {
    toggleChat(true);
    const widget = document.querySelector(CHAT_WIDGET_SELECTOR);
    if (!widget) return;
    const textarea = widget.querySelector("textarea[name='question']");
    if (!textarea) return;
    textarea.value = prompt;
    textarea.focus({ preventScroll: false });
  }
})();
function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(value) {
  const stringValue = String(value);
  return stringValue.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

function highlightMatch(text, query) {
  const safeText = escapeHtml(text);
  if (!query) return safeText;
  const pattern = escapeRegExp(query.trim());
  if (!pattern) return safeText;
  const regex = new RegExp(`(${pattern})`, "ig");
  return safeText.replace(regex, "<mark>$1</mark>");
}

function uniqueId(prefix = "id") {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}
