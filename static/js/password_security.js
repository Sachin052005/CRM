/**
 * TECHPANDA CRM - Password Security & Strength Engine
 * Provides real-time password strength validation, rule indicators,
 * password matching validation, and show/hide password toggles.
 */

document.addEventListener('DOMContentLoaded', function () {
  initPasswordToggles();
  initPasswordMatchValidation();
});

function initPasswordToggles() {
  const passwordInputs = document.querySelectorAll('input[type="password"]');

  passwordInputs.forEach(input => {
    // Avoid double initialization
    if (input.dataset.toggleInitialized) return;
    input.dataset.toggleInitialized = 'true';

    // Wrap in a relative container if not already styled for positioning
    const parent = input.parentElement;
    if (parent && !parent.classList.contains('pwd-toggle-wrapper')) {
      const wrapper = document.createElement('div');
      wrapper.className = 'pwd-toggle-wrapper';
      wrapper.style.position = 'relative';
      wrapper.style.display = 'block';

      parent.insertBefore(wrapper, input);
      wrapper.appendChild(input);

      input.style.paddingRight = '42px';

      const toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'pwd-toggle-btn';
      toggleBtn.setAttribute('aria-label', 'Toggle password visibility');
      toggleBtn.innerHTML = eyeIconSvg(false);
      toggleBtn.style.position = 'absolute';
      toggleBtn.style.right = '8px';
      toggleBtn.style.top = '50%';
      toggleBtn.style.transform = 'translateY(-50%)';
      toggleBtn.style.background = 'none';
      toggleBtn.style.border = 'none';
      toggleBtn.style.cursor = 'pointer';
      toggleBtn.style.padding = '4px 6px';
      toggleBtn.style.display = 'flex';
      toggleBtn.style.alignItems = 'center';
      toggleBtn.style.color = '#64748b';
      toggleBtn.style.zIndex = '2';

      toggleBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (input.type === 'password') {
          input.type = 'text';
          toggleBtn.innerHTML = eyeIconSvg(true);
          toggleBtn.style.color = 'var(--primary, #2563eb)';
        } else {
          input.type = 'password';
          toggleBtn.innerHTML = eyeIconSvg(false);
          toggleBtn.style.color = '#64748b';
        }
      });

      wrapper.appendChild(toggleBtn);
    }
  });
}

function initPasswordMatchValidation() {
  // Live "passwords match" / "do not match" feedback only - the visual strength meter/rule
  // bar is intentionally not rendered on this flow, but the underlying complexity check
  // still runs server-side via Django's AUTH_PASSWORD_VALIDATORS (see config/settings.py)
  // and accounts/validators.py ComplexityValidator, so real validation is unaffected.
  const passwordInputs = document.querySelectorAll(
    'input[name="password"], input[name="new_password1"], input[id$="new_password1"], input[data-meter="true"]'
  );

  passwordInputs.forEach(pwdInput => {
    if (pwdInput.dataset.matchInitialized) return;
    pwdInput.dataset.matchInitialized = 'true';

    const form = pwdInput.closest('form');
    const confirmInput = form ? form.querySelector('input[name="confirm_password"], input[name="new_password2"]') : null;
    if (!confirmInput) return;

    const matchMsgBox = document.createElement('div');
    matchMsgBox.style.fontSize = '0.775rem';
    matchMsgBox.style.marginTop = '4px';
    matchMsgBox.style.fontWeight = '500';
    const confirmWrapper = confirmInput.closest('.pwd-toggle-wrapper') || confirmInput;
    confirmWrapper.parentNode.insertBefore(matchMsgBox, confirmWrapper.nextSibling);

    function checkMatch() {
      const cVal = confirmInput.value;
      const pVal = pwdInput.value;

      if (!cVal) {
        matchMsgBox.innerHTML = '';
        return;
      }

      if (pVal === cVal) {
        matchMsgBox.innerHTML = '<span style="color: #10b981;">✓ Passwords match</span>';
      } else {
        matchMsgBox.innerHTML = '<span style="color: #ef4444;">✕ Passwords do not match</span>';
      }
    }

    pwdInput.addEventListener('input', checkMatch);
    confirmInput.addEventListener('input', checkMatch);
  });
}

function initPasswordStrengthMeters() {
  // Find creation / change password fields
  const targetInputs = document.querySelectorAll(
    'input[name="password"], input[name="new_password1"], input[id$="new_password1"], input[data-meter="true"]'
  );

  targetInputs.forEach(pwdInput => {
    if (pwdInput.dataset.meterInitialized) return;
    pwdInput.dataset.meterInitialized = 'true';

    // Find confirm password field if present in the same form
    const form = pwdInput.closest('form');
    const confirmInput = form ? form.querySelector('input[name="confirm_password"], input[name="new_password2"]') : null;

    // Create container for meter
    const meterBox = document.createElement('div');
    meterBox.className = 'password-strength-box';
    meterBox.style.marginTop = '8px';
    meterBox.style.marginBottom = '8px';
    meterBox.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; font-size: 0.775rem;">
        <span style="color: #64748b; font-weight: 500;">Password Strength:</span>
        <strong id="pwd-strength-label-${pwdInput.name}" style="color: #94a3b8; font-weight: 600;">None</strong>
      </div>
      <div style="display: flex; gap: 4px; height: 5px; width: 100%; background: #e2e8f0; border-radius: 4px; overflow: hidden; margin-bottom: 6px;">
        <div id="bar-seg-1-${pwdInput.name}" style="flex: 1; height: 100%; background: transparent; transition: background 0.2s;"></div>
        <div id="bar-seg-2-${pwdInput.name}" style="flex: 1; height: 100%; background: transparent; transition: background 0.2s;"></div>
        <div id="bar-seg-3-${pwdInput.name}" style="flex: 1; height: 100%; background: transparent; transition: background 0.2s;"></div>
      </div>
      <div id="pwd-rules-${pwdInput.name}" style="display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 0.725rem; color: #64748b; line-height: 1.3;">
        <span id="rule-len-${pwdInput.name}">○ 8+ chars (10+ rec)</span>
        <span id="rule-upper-${pwdInput.name}">○ Uppercase</span>
        <span id="rule-lower-${pwdInput.name}">○ Lowercase</span>
        <span id="rule-num-${pwdInput.name}">○ Number</span>
        <span id="rule-special-${pwdInput.name}">○ Special symbol</span>
      </div>
    `;

    // Insert after the input or its wrapper
    const insertAfterNode = pwdInput.closest('.pwd-toggle-wrapper') || pwdInput;
    insertAfterNode.parentNode.insertBefore(meterBox, insertAfterNode.nextSibling);

    let matchMsgBox = null;
    if (confirmInput) {
      matchMsgBox = document.createElement('div');
      matchMsgBox.style.fontSize = '0.775rem';
      matchMsgBox.style.marginTop = '4px';
      matchMsgBox.style.fontWeight = '500';
      const confirmWrapper = confirmInput.closest('.pwd-toggle-wrapper') || confirmInput;
      confirmWrapper.parentNode.insertBefore(matchMsgBox, confirmWrapper.nextSibling);
    }

    function evaluate() {
      const val = pwdInput.value;
      const res = calculateComplexity(val);

      const label = document.getElementById(`pwd-strength-label-${pwdInput.name}`);
      const seg1 = document.getElementById(`bar-seg-1-${pwdInput.name}`);
      const seg2 = document.getElementById(`bar-seg-2-${pwdInput.name}`);
      const seg3 = document.getElementById(`bar-seg-3-${pwdInput.name}`);

      updateRule('rule-len-' + pwdInput.name, res.hasMinLength);
      updateRule('rule-upper-' + pwdInput.name, res.hasUpper);
      updateRule('rule-lower-' + pwdInput.name, res.hasLower);
      updateRule('rule-num-' + pwdInput.name, res.hasDigit);
      updateRule('rule-special-' + pwdInput.name, res.hasSpecial);

      if (!val) {
        label.textContent = "None";
        label.style.color = "#94a3b8";
        seg1.style.background = "transparent";
        seg2.style.background = "transparent";
        seg3.style.background = "transparent";
      } else if (res.score === 1) {
        label.textContent = "Weak";
        label.style.color = "#ef4444";
        seg1.style.background = "#ef4444";
        seg2.style.background = "transparent";
        seg3.style.background = "transparent";
      } else if (res.score === 2) {
        label.textContent = "Medium";
        label.style.color = "#f59e0b";
        seg1.style.background = "#f59e0b";
        seg2.style.background = "#f59e0b";
        seg3.style.background = "transparent";
      } else {
        label.textContent = "Strong";
        label.style.color = "#10b981";
        seg1.style.background = "#10b981";
        seg2.style.background = "#10b981";
        seg3.style.background = "#10b981";
      }

      checkMatch();
    }

    function checkMatch() {
      if (!confirmInput || !matchMsgBox) return;
      const cVal = confirmInput.value;
      const pVal = pwdInput.value;

      if (!cVal) {
        matchMsgBox.innerHTML = '';
        return;
      }

      if (pVal === cVal) {
        matchMsgBox.innerHTML = '<span style="color: #10b981;">✓ Passwords match</span>';
      } else {
        matchMsgBox.innerHTML = '<span style="color: #ef4444;">✕ Passwords do not match</span>';
      }
    }

    pwdInput.addEventListener('input', evaluate);
    if (confirmInput) {
      confirmInput.addEventListener('input', checkMatch);
    }
  });
}

function updateRule(elementId, passed) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (passed) {
    el.style.color = '#10b981';
    el.style.fontWeight = '600';
    if (!el.textContent.startsWith('✓ ')) {
      el.textContent = '✓ ' + el.textContent.replace(/^[○✓]\s*/, '');
    }
  } else {
    el.style.color = '#64748b';
    el.style.fontWeight = 'normal';
    if (!el.textContent.startsWith('○ ')) {
      el.textContent = '○ ' + el.textContent.replace(/^[○✓]\s*/, '');
    }
  }
}

function calculateComplexity(pwd) {
  if (!pwd) return { score: 0, hasMinLength: false, hasUpper: false, hasLower: false, hasDigit: false, hasSpecial: false };

  const hasMinLength = pwd.length >= 8;
  const hasPreferredLength = pwd.length >= 10;
  const hasUpper = /[A-Z]/.test(pwd);
  const hasLower = /[a-z]/.test(pwd);
  const hasDigit = /[0-9]/.test(pwd);
  const hasSpecial = /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`"']/.test(pwd);

  const passedRules = [hasMinLength, hasUpper, hasLower, hasDigit, hasSpecial].filter(Boolean).length;

  let score = 1; // Weak
  if (passedRules >= 5) {
    score = hasPreferredLength ? 3 : 2; // Strong if >=10, Medium if 8-9
  } else if (passedRules >= 3 && hasMinLength) {
    score = 2; // Medium
  } else {
    score = 1; // Weak
  }

  return {
    score,
    hasMinLength,
    hasPreferredLength,
    hasUpper,
    hasLower,
    hasDigit,
    hasSpecial
  };
}

function eyeIconSvg(showPassword) {
  if (showPassword) {
    // Eye off
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
      <line x1="1" y1="1" x2="23" y2="23"></line>
    </svg>`;
  } else {
    // Eye
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
      <circle cx="12" cy="12" r="3"></circle>
    </svg>`;
  }
}
