/**
 * TECHPANDA CRM - Interactive Client Scripts
 * Handles: Theme toggle, Sidebar state persistence, Confirmation dialogs, Live Call Dialer
 */

(function () {
  'use strict';

  // 1. Theme Management (Light / Dark)
  const THEME_KEY = 'techpanda_theme';
  const themeToggleBtn = document.getElementById('theme-toggle');

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    if (themeToggleBtn) {
      const sunIcon = themeToggleBtn.querySelector('.icon-sun');
      const moonIcon = themeToggleBtn.querySelector('.icon-moon');
      if (theme === 'dark') {
        if (sunIcon) sunIcon.style.display = 'inline-block';
        if (moonIcon) moonIcon.style.display = 'none';
      } else {
        if (sunIcon) sunIcon.style.display = 'none';
        if (moonIcon) moonIcon.style.display = 'inline-block';
      }
    }
  }

  const savedTheme = localStorage.getItem(THEME_KEY) || 'light';
  applyTheme(savedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', function () {
      const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(newTheme);
    });
  }

  // 2. Sidebar Persistence and Collapse
  const SIDEBAR_KEY = 'techpanda_sidebar_collapsed';
  const sidebar = document.querySelector('.app-sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');

  if (sidebar && sidebarToggle) {
    const isCollapsed = localStorage.getItem(SIDEBAR_KEY) === 'true';
    if (isCollapsed && window.innerWidth > 900) {
      sidebar.classList.add('collapsed');
    }

    sidebarToggle.addEventListener('click', function () {
      if (window.innerWidth <= 900) {
        sidebar.classList.toggle('mobile-open');
      } else {
        sidebar.classList.toggle('collapsed');
        localStorage.setItem(SIDEBAR_KEY, sidebar.classList.contains('collapsed'));
      }
    });
  }

  // 3. Confirmation Dialogs for Destructive Actions
  document.addEventListener('click', function (e) {
    const confirmBtn = e.target.closest('[data-confirm]');
    if (confirmBtn) {
      const message = confirmBtn.getAttribute('data-confirm') || 'Are you sure you want to perform this action?';
      if (!window.confirm(message)) {
        e.preventDefault();
        e.stopPropagation();
      }
    }
  });

  // Helper: CSRF Cookie reader
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // 4. Live Call Timer & Mandatory Call-Notes Lock Workflow
  let callTimerInterval = null;
  let callSeconds = 0;
  let currentActiveCallId = null;

  function formatDuration(sec) {
    const hrs = Math.floor(sec / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    const secs = sec % 60;
    if (hrs > 0) {
      return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function showCallNotesRequiredModal(pendingCall) {
    const lockModal = document.getElementById('call-notes-required-modal');
    if (!lockModal) {
      alert('You have a completed call that still requires notes before calling another lead.');
      return;
    }
    const leadNameEl = document.getElementById('lock-modal-lead-name');
    const leadPhoneEl = document.getElementById('lock-modal-lead-phone');
    if (leadNameEl) leadNameEl.textContent = pendingCall.lead_name || 'Assigned Lead';
    if (leadPhoneEl) leadPhoneEl.textContent = pendingCall.lead_phone || '-';

    const addNotesBtn = document.getElementById('lock-modal-add-notes-btn');
    if (addNotesBtn) {
      addNotesBtn.onclick = function () {
        lockModal.style.display = 'none';
        openCompletionFormForPendingCall(pendingCall);
      };
    }
    lockModal.style.display = 'flex';
  }

  function openCompletionFormForPendingCall(pendingCall) {
    const overlay = document.getElementById('call-dialer-overlay');
    if (!overlay) return;

    if (callTimerInterval) clearInterval(callTimerInterval);

    currentActiveCallId = pendingCall.id;
    callSeconds = pendingCall.duration || 0;

    const callInput = document.getElementById('call-form-call-id');
    if (callInput) callInput.value = pendingCall.id;

    const leadInput = document.getElementById('call-form-lead-id');
    if (leadInput) leadInput.value = pendingCall.lead_id;

    const durationInput = document.getElementById('call-form-duration');
    if (durationInput) durationInput.value = callSeconds;

    const compName = document.getElementById('completion-lead-name');
    if (compName) compName.textContent = pendingCall.lead_name;

    const compPhone = document.getElementById('completion-lead-phone');
    if (compPhone) compPhone.textContent = pendingCall.lead_phone;

    const compDur = document.getElementById('completion-lead-duration');
    if (compDur) compDur.textContent = pendingCall.formatted_duration || formatDuration(callSeconds);

    const notesInput = document.getElementById('call-form-notes');
    if (notesInput) {
      notesInput.value = '';
      setTimeout(() => notesInput.focus(), 150);
    }
    const notesErr = document.getElementById('call-form-notes-error');
    if (notesErr) notesErr.style.display = 'none';

    document.getElementById('dialer-calling-state').style.display = 'none';
    document.getElementById('dialer-completion-form').style.display = 'block';
    overlay.classList.add('active');
  }

  function startDialerUI(callId, leadId, leadName, leadPhone) {
    const overlay = document.getElementById('call-dialer-overlay');
    if (!overlay) return;

    currentActiveCallId = callId;
    callSeconds = 0;

    document.getElementById('dialer-lead-name').textContent = leadName;
    document.getElementById('dialer-lead-phone').textContent = leadPhone;
    document.getElementById('dialer-timer-display').textContent = '00:00:00';
    document.getElementById('dialer-calling-state').style.display = 'block';
    document.getElementById('dialer-completion-form').style.display = 'none';

    const callInput = document.getElementById('call-form-call-id');
    if (callInput) callInput.value = callId;

    const leadInput = document.getElementById('call-form-lead-id');
    if (leadInput) leadInput.value = leadId;

    const compName = document.getElementById('completion-lead-name');
    if (compName) compName.textContent = leadName;

    const compPhone = document.getElementById('completion-lead-phone');
    if (compPhone) compPhone.textContent = leadPhone;

    const sanitizedPhone = (leadPhone || '').replace(/[^\d+]/g, '');
    const nativeLink = document.getElementById('dialer-native-link');
    if (nativeLink) {
      nativeLink.href = 'tel:' + sanitizedPhone;
    }
    try {
      window.location.href = 'tel:' + sanitizedPhone;
    } catch (e) {
      // Ignore protocol handler fallback
    }

    overlay.classList.add('active');

    if (callTimerInterval) clearInterval(callTimerInterval);
    callTimerInterval = setInterval(function () {
      callSeconds++;
      document.getElementById('dialer-timer-display').textContent = formatDuration(callSeconds);
    }, 1000);
  }

  window.openCallDialer = function (leadId, leadName, leadPhone) {
    // Call backend start endpoint to verify Call-Notes Lock
    const csrfToken = getCookie('csrftoken') || '';
    const formData = new FormData();
    formData.append('lead_id', leadId);

    fetch('/calls/start/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken,
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: formData
    })
    .then(r => r.json().then(data => ({ status: r.status, ok: r.ok, data: data })))
    .then(res => {
      if (res.status === 400 && res.data.blocked) {
        showCallNotesRequiredModal(res.data.pending_call);
        return;
      }
      if (!res.ok || !res.data.success) {
        alert(res.data.error || 'Failed to start call.');
        return;
      }
      // Start call UI
      startDialerUI(res.data.call_id, res.data.lead_id, res.data.lead_name || leadName, res.data.lead_phone || leadPhone);
    })
    .catch(err => {
      console.error('Call start error:', err);
      // Fallback: check lock via GET if POST fails unexpectedly
      fetch(`/calls/start/?lead_id=${leadId}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
      .then(r => r.json().then(data => ({ status: r.status, ok: r.ok, data: data })))
      .then(res => {
        if (res.status === 400 && res.data.blocked) {
          showCallNotesRequiredModal(res.data.pending_call);
        } else if (res.data.success) {
          startDialerUI(res.data.call_id, res.data.lead_id, res.data.lead_name || leadName, res.data.lead_phone || leadPhone);
        }
      });
    });
  };

  window.endActiveCall = function () {
    if (callTimerInterval) clearInterval(callTimerInterval);

    // Call backend end endpoint
    if (currentActiveCallId) {
      const formData = new FormData();
      formData.append('duration', callSeconds);
      fetch(`/calls/${currentActiveCallId}/end/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken') || '',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData
      }).catch(err => console.warn('Call end notify failed:', err));
    }

    // Switch to completion form
    document.getElementById('dialer-calling-state').style.display = 'none';
    document.getElementById('dialer-completion-form').style.display = 'block';

    const durationInput = document.getElementById('call-form-duration');
    if (durationInput) durationInput.value = callSeconds;

    const compDur = document.getElementById('completion-lead-duration');
    if (compDur) compDur.textContent = formatDuration(callSeconds);

    const notesInput = document.getElementById('call-form-notes');
    if (notesInput) {
      notesInput.value = '';
      setTimeout(() => notesInput.focus(), 100);
    }
  };

  window.closeCallDialer = function () {
    if (callTimerInterval) clearInterval(callTimerInterval);
    const overlay = document.getElementById('call-dialer-overlay');
    if (overlay) overlay.classList.remove('active');
  };

  // Bind Call Notes Completion Form
  const completionForm = document.getElementById('call-notes-completion-form');
  if (completionForm) {
    completionForm.addEventListener('submit', function (e) {
      const notesInput = document.getElementById('call-form-notes');
      const notesErr = document.getElementById('call-form-notes-error');
      const notesVal = (notesInput ? notesInput.value : '').trim();

      if (!notesVal) {
        e.preventDefault();
        if (notesErr) {
          notesErr.textContent = 'Call Notes are required before completing this call.';
          notesErr.style.display = 'block';
        }
        if (notesInput) notesInput.focus();
        return false;
      }
      if (notesErr) notesErr.style.display = 'none';

      e.preventDefault();
      const submitBtn = document.getElementById('save-call-notes-btn');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving Call Notes...';
      }

      const formData = new FormData(completionForm);
      fetch('/calls/complete/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken') || '',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData
      })
      .then(r => r.json().then(data => ({ status: r.status, ok: r.ok, data: data })))
      .then(res => {
        if (!res.ok || !res.data.success) {
          if (notesErr) {
            notesErr.textContent = res.data.error || 'Failed to save call notes.';
            notesErr.style.display = 'block';
          } else {
            alert(res.data.error || 'Failed to save call notes.');
          }
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save Call Notes';
          }
          return;
        }

        // Unlocked!
        currentActiveCallId = null;
        const overlay = document.getElementById('call-dialer-overlay');
        if (overlay) overlay.classList.remove('active');
        alert('✓ ' + (res.data.message || 'Call notes saved successfully. You can now call another lead.'));
        window.location.reload();
      })
      .catch(err => {
        console.error('Call completion error:', err);
        alert('An unexpected error occurred while saving call notes.');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Save Call Notes';
        }
      });
    });
  }

  const notifBellBtn = document.getElementById('notification-bell-btn');
  const notifPanel = document.getElementById('notification-panel');
  const notifContainer = document.getElementById('notification-items-container');
  const notifBadge = document.getElementById('notif-badge-count');
  const markAllReadBtn = document.getElementById('mark-all-read-btn');

  function renderNotifications(items) {
    if (!notifContainer) return;
    if (!items || items.length === 0) {
      notifContainer.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 0.85rem;">No notifications right now.</div>';
      return;
    }
    let html = '';
    items.forEach(function (n) {
      const bg = n.is_read ? 'transparent' : 'rgba(37, 99, 235, 0.05)';
      html += `
        <div class="notif-item" data-id="${n.id}" style="padding: 10px 14px; border-bottom: 1px solid var(--border-color); background: ${bg}; display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
          <div style="flex: 1;">
            <div style="font-size: 0.825rem; font-weight: 600; color: var(--text-main); margin-bottom: 2px;">${n.title}</div>
            <div style="font-size: 0.775rem; color: var(--text-muted); line-height: 1.3; margin-bottom: 4px;">${n.message}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">${n.timestamp}</div>
          </div>
          ${!n.is_read ? `<button type="button" class="btn-mark-single-read" data-id="${n.id}" style="background: none; border: none; color: var(--primary); font-size: 0.8rem; cursor: pointer; padding: 2px 6px; font-weight: bold;" title="Mark read">✓</button>` : ''}
        </div>
      `;
    });
    notifContainer.innerHTML = html;
  }

  function loadNotifications() {
    fetch('/notifications/latest/')
      .then(r => r.json())
      .then(data => {
        if (notifBadge) {
          notifBadge.textContent = data.unread_count;
          notifBadge.style.display = data.unread_count > 0 ? 'inline-block' : 'none';
        }
        renderNotifications(data.notifications);
      })
      .catch(err => console.warn('Failed to load notifications:', err));
  }

  if (notifBellBtn && notifPanel) {
    notifBellBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      const isVisible = notifPanel.style.display === 'flex';
      if (isVisible) {
        notifPanel.style.display = 'none';
      } else {
        notifPanel.style.display = 'flex';
        loadNotifications();
      }
    });

    document.addEventListener('click', function (e) {
      if (!notifPanel.contains(e.target) && e.target !== notifBellBtn) {
        notifPanel.style.display = 'none';
      }
    });
  }

  if (markAllReadBtn) {
    markAllReadBtn.addEventListener('click', function (e) {
      e.preventDefault();
      fetch('/notifications/mark-all-read/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken') || '',
          'Content-Type': 'application/json'
        }
      })
      .then(r => r.json())
      .then(() => {
        if (notifBadge) {
          notifBadge.textContent = '0';
          notifBadge.style.display = 'none';
        }
        loadNotifications();
      });
    });
  }

  if (notifContainer) {
    notifContainer.addEventListener('click', function (e) {
      const markBtn = e.target.closest('.btn-mark-single-read');
      if (markBtn) {
        e.stopPropagation();
        const notifId = markBtn.getAttribute('data-id');
        fetch(`/notifications/${notifId}/mark-read/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken') || '',
            'Content-Type': 'application/json'
          }
        })
        .then(r => r.json())
        .then(() => loadNotifications());
      }
    });
  }

})();
