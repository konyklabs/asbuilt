const CHECKOUT_REFUSALS = {
  checkout_limit_reached: "You already hold as many bikes as one rider can. Dock one, then try again.",
  bike_locked: "That bike is locked for maintenance. Pick another one.",
};

const REFUND_REFUSALS = {
  refund_window_expired: "This ride is too old to refund: the refund window has closed.",
  refund_exceeds_charge: "A refund cannot be more than the ride cost.",
};

function formatCents(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

async function callApi(method, path, payload) {
  const init = { method, headers: { Accept: "application/json" } };
  if (payload !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  const response = await fetch(path, init);
  return { status: response.status, body: await response.json() };
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function previewFare(form) {
  const values = formValues(form);
  const query = new URLSearchParams({
    minutes: values.minutes,
    member: values.member ? "1" : "0",
    ebike: values.ebike ? "1" : "0",
  });
  return callApi("GET", `/api/fares/preview?${query}`);
}

function initFarePreview() {
  const form = document.getElementById("fare-preview-form");
  const amount = document.getElementById("fare-amount");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const { status, body } = await previewFare(form);
    amount.textContent = status === 200 ? formatCents(body.amount_cents) : "unavailable";
  });
}

function initCheckOut() {
  const form = document.getElementById("check-out-form");
  const banner = document.getElementById("checkout-banner");
  const result = document.getElementById("checkout-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    banner.hidden = true;
    result.textContent = "";
    const { status, body } = await callApi("POST", "/api/rides/checkout", formValues(form));
    if (status === 201) {
      result.textContent = `Ride ${body.ride_id} started.`;
      return;
    }
    banner.textContent = CHECKOUT_REFUSALS[body.error] ?? "Check-out failed.";
    banner.hidden = false;
  });
}

function initRefundRequest() {
  const form = document.getElementById("refund-request-form");
  const result = document.getElementById("refund-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = formValues(form);
    const { status, body } = await callApi("POST", "/api/refunds", {
      ride_id: values.ride_id,
      ride_ended_at: values.ride_ended_at,
      charged_cents: Number(values.charged_cents),
      requested_cents: Number(values.requested_cents),
    });
    result.textContent =
      status === 201 ? `Refund ${body.status}.` : (REFUND_REFUSALS[body.error] ?? "Refund failed.");
  });
}

const PAGES = {
  "fare-preview": initFarePreview,
  "check-out": initCheckOut,
  "refund-request": initRefundRequest,
};

PAGES[document.body.dataset.page]?.();
