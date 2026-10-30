// Each action copies one purpose-specific reference from this deployment.
(() => {
  const content = {
    version: ['citationText', 'citationDoi', 'citationStatus'],
    methods: ['citationMethods', null, 'methodsStatus'],
    project: ['citationConceptText', 'citationConceptDoi', 'projectCitationStatus'],
  };
  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const [textId, linkId, statusId] = content[button.dataset.copy];
      const text = document.getElementById(textId).textContent.trim();
      const citation = linkId ? text + ' ' + document.getElementById(linkId).href : text;
      const status = document.getElementById(statusId);
      try {
        await navigator.clipboard.writeText(citation);
        status.textContent = button.dataset.copy === 'methods' ? 'Methods sentence copied.' : 'Citation copied.';
      } catch {
        status.textContent = 'Select the text above to copy it.';
      }
    });
  });
})();
