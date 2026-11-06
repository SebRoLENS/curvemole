// Capture metadata follows the published stable build; no client-side fit is run.
const quickStartManifest = 'assets/quick-start/manifest.json';

async function loadCaptureRecord() {
  const status = document.getElementById('qs-manifest-status');
  try {
    const response = await fetch(quickStartManifest, {cache: 'no-cache'});
    if (!response.ok) throw new Error('Capture record unavailable');
    const record = await response.json();
    const version = record.version || record.curvemole_version || record.application_version;
    if (typeof version === 'string' && version.length < 80) {
      document.querySelectorAll('[data-capture-version]').forEach(node => {
        node.textContent = 'CurveMole ' + version;
      });
    }
    const rho = record.fit?.overlap_area_correlation;
    if (typeof rho === 'number' && Number.isFinite(rho) && rho >= -1 && rho <= 1) {
      document.querySelectorAll('[data-overlap-correlation]').forEach(node => {
        node.textContent = 'r = ' + rho.toFixed(3).replace('-', '−');
      });
    }
    const mcRho = record.fit?.monte_carlo?.overlap_area_correlation;
    if (typeof mcRho === 'number' && Number.isFinite(mcRho) && mcRho >= -1 && mcRho <= 1) {
      document.querySelectorAll('[data-mc-overlap-correlation]').forEach(node => {
        node.textContent = 'r = ' + mcRho.toFixed(3).replace('-', '−');
      });
    }
    const source = record.capture_sha || record.source_sha || record.git_sha || version;
    if (typeof source === 'string' && source.length < 150) {
      const query = '?capture=' + encodeURIComponent(source);
      document.querySelectorAll('[data-qs-screenshot]').forEach(img => {
        img.src = img.getAttribute('src').split('?')[0] + query;
      });
      document.querySelectorAll('[data-qs-screenshot-link]').forEach(link => {
        link.href = link.getAttribute('href').split('?')[0] + query;
      });
    }
    if (status) status.textContent = version
      ? 'These captures and the recorded numerical result were generated with CurveMole ' + version + '.'
      : 'The capture manifest is available; inspect it for the software source and numerical result.';
  } catch {
    if (status) status.textContent = 'The capture metadata could not be loaded. Open the capture record to check the version of the available screenshots.';
  }
}

const quickStartLinks = [...document.querySelectorAll('.qs-toc a[href^="#"]')];
const quickStartSections = [...document.querySelectorAll('.qs-step[id]')];
function setCurrentStep(id) {
  quickStartLinks.forEach(link => {
    if (link.getAttribute('href') === '#' + id) link.setAttribute('aria-current', 'step');
    else link.removeAttribute('aria-current');
  });
}
if ('IntersectionObserver' in window) {
  const stepObserver = new IntersectionObserver(entries => {
    entries.filter(entry => entry.isIntersecting).forEach(entry => setCurrentStep(entry.target.id));
  }, {rootMargin: '-15% 0px -65% 0px', threshold: 0});
  quickStartSections.forEach(section => stepObserver.observe(section));
}
quickStartLinks.forEach(link => link.addEventListener('click', () => {
  setCurrentStep(link.getAttribute('href').slice(1));
}));
loadCaptureRecord();
