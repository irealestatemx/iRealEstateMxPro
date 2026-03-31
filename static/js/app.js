// ===========================
// iRealEstateMxPro — app.js
// ===========================

/* ── Price formatter ── */
const precioInput = document.getElementById('precio');
const precioDisplay = document.getElementById('precio-display');

if (precioInput) {
  precioInput.addEventListener('input', () => {
    const raw = precioInput.value.replace(/\D/g, '');
    if (raw) {
      const formatted = Number(raw).toLocaleString('es-MX');
      precioDisplay.textContent = `$ ${formatted} MXN`;
    } else {
      precioDisplay.textContent = '';
    }
  });
}

/* ── Photo preview ── */
const fotosInput = document.getElementById('fotos');
const photoPreview = document.getElementById('photoPreview');
const uploadPlaceholder = document.getElementById('uploadPlaceholder');

if (fotosInput) {
  fotosInput.addEventListener('change', renderPreviews);
}

function renderPreviews() {
  photoPreview.innerHTML = '';
  const files = Array.from(fotosInput.files);

  if (files.length === 0) {
    if (uploadPlaceholder) uploadPlaceholder.style.display = 'block';
    return;
  }
  if (uploadPlaceholder) uploadPlaceholder.style.display = 'none';

  files.forEach((file, index) => {
    if (!file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const item = document.createElement('div');
      item.className = 'preview-item' + (index === 0 ? ' cover-preview' : '');

      const img = document.createElement('img');
      img.src = e.target.result;
      img.alt = file.name;
      item.appendChild(img);

      if (index === 0) {
        const label = document.createElement('div');
        label.className = 'cover-label';
        label.textContent = 'Portada';
        item.appendChild(label);
      }
      photoPreview.appendChild(item);
    };
    reader.readAsDataURL(file);
  });
}

/* ── Drag & drop on upload area ── */
const uploadArea = document.getElementById('uploadArea');
if (uploadArea) {
  uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('drag-over');
  });
  uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('drag-over');
  });
  uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
      fotosInput.files = e.dataTransfer.files;
      renderPreviews();
    }
  });
}

/* ── Form submit → loading overlay ── */
const propertyForm = document.getElementById('propertyForm');
const loadingOverlay = document.getElementById('loadingOverlay');
const submitBtn = document.getElementById('submitBtn');

if (propertyForm) {
  propertyForm.addEventListener('submit', (e) => {
    // Basic validation
    const required = propertyForm.querySelectorAll('[required]');
    let valid = true;
    required.forEach((field) => {
      field.style.borderColor = '';
      if (!field.value.trim()) {
        field.style.borderColor = '#dc3545';
        valid = false;
      }
    });

    if (!valid) {
      e.preventDefault();
      const firstInvalid = propertyForm.querySelector('[required]:invalid, [style*="dc3545"]');
      if (firstInvalid) firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    if (loadingOverlay) loadingOverlay.classList.add('active');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.querySelector('.btn-text').textContent = 'Generando...';
    }
  });
}

/* ── Copy to clipboard ── */
function copyToClipboard(elementId, btn) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.innerText || el.textContent;

  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('copied');
    btn.innerHTML = '<span class="copy-icon">✓</span> ¡Copiado!';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = '<span class="copy-icon">📋</span> Copiar';
    }, 2500);
  }).catch(() => {
    // Fallback for browsers without clipboard API
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.classList.add('copied');
    btn.innerHTML = '<span class="copy-icon">✓</span> ¡Copiado!';
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = '<span class="copy-icon">📋</span> Copiar';
    }, 2500);
  });
}

/* ── Toast notification ── */
function showToast(message, isSuccess) {
  const toast = document.getElementById('toast');
  const toastIcon = document.getElementById('toastIcon');
  const toastMsg = document.getElementById('toastMsg');
  if (!toast) return;

  toastIcon.textContent = isSuccess ? '✅' : '❌';
  toastMsg.textContent = message;
  toast.className = 'toast ' + (isSuccess ? 'toast-success' : 'toast-error') + ' toast-visible';

  setTimeout(() => { toast.classList.remove('toast-visible'); }, 5000);
}

/* ── Publish to Instagram via Upload Post API ── */
async function publishToInstagram() {
  const btn = document.getElementById('publishIgBtn');
  if (!btn) return;

  // Deshabilitar boton
  btn.disabled = true;
  btn.innerHTML = '<span>⏳</span> Publicando...';

  // Recoger datos del form oculto de imagen
  const imgForm = document.getElementById('imgForm');
  const formData = new FormData(imgForm);

  // Agregar el instagram_copy desde el contenido de la pagina
  const igCopyEl = document.getElementById('instagram-copy');
  if (igCopyEl) {
    formData.append('instagram_copy', igCopyEl.innerText || igCopyEl.textContent);
  }

  try {
    const response = await fetch('/publish-instagram', {
      method: 'POST',
      body: formData,
    });
    const result = await response.json();

    if (result.success) {
      let msg = result.message;
      if (result.post_url) msg += ' — ' + result.post_url;
      showToast(msg, true);
      btn.innerHTML = '<span>✅</span> Publicado';
    } else {
      showToast('Error: ' + (result.error || 'Error desconocido'), false);
      btn.disabled = false;
      btn.innerHTML = '<span>🚀</span> Publicar en Instagram';
    }
  } catch (err) {
    showToast('Error de conexion: ' + err.message, false);
    btn.disabled = false;
    btn.innerHTML = '<span>🚀</span> Publicar en Instagram';
  }
}
