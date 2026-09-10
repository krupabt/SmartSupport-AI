/**
 * SmartSupport AI — Frontend Application Logic & Toast Notification Manager
 */

document.addEventListener("DOMContentLoaded", () => {
  // Initialize all Bootstrap tooltips if any
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));

  // Initialize all Bootstrap toasts rendered from server flashes
  const toastElList = [].slice.call(document.querySelectorAll('.toast'));
  toastElList.map(toastEl => {
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
    toast.show();
  });
});

/**
 * Global dynamic toast notification trigger.
 * @param {string} message - The message content.
 * @param {string} type - 'success', 'danger', 'warning', 'info'.
 * @param {string} title - Optional title.
 */
function showToast(message, type = "info", title = "") {
  let toastContainer = document.querySelector(".toast-container");
  if (!toastContainer) {
    toastContainer = document.createElement("div");
    toastContainer.className = "toast-container position-fixed top-0 end-0 p-3";
    toastContainer.style.zIndex = "1090";
    document.body.appendChild(toastContainer);
  }

  const iconMap = {
    success: "bi-check-circle-fill text-success",
    danger: "bi-exclamation-octagon-fill text-danger",
    warning: "bi-exclamation-triangle-fill text-warning",
    info: "bi-info-circle-fill text-primary"
  };

  const defaultTitles = {
    success: "Success",
    danger: "Error",
    warning: "Notice",
    info: "Information"
  };

  const toastId = "toast-" + Date.now();
  const displayTitle = title || defaultTitles[type] || "Notification";
  const iconClass = iconMap[type] || iconMap.info;

  const toastHtml = `
    <div id="${toastId}" class="toast custom-toast border-0 shadow-lg" role="alert" aria-live="assertive" aria-atomic="true">
      <div class="toast-header bg-white border-bottom">
        <i class="bi ${iconClass} me-2 fs-5"></i>
        <strong class="me-auto text-dark">${displayTitle}</strong>
        <small class="text-muted">Just now</small>
        <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
      <div class="toast-body bg-white text-secondary py-3">
        ${message}
      </div>
    </div>
  `;

  toastContainer.insertAdjacentHTML("beforeend", toastHtml);
  const newToastEl = document.getElementById(toastId);
  const toastInstance = new bootstrap.Toast(newToastEl, { delay: 4500 });
  
  newToastEl.addEventListener('hidden.bs.toast', () => {
    newToastEl.remove();
  });

  toastInstance.show();
}
