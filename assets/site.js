/* Progressive enhancement: every term remains a normal link without JavaScript. */
(() => {
  'use strict';
  const dialog = document.querySelector('#term-dialog');
  const content = document.querySelector('#term-dialog-content');
  let returnFocus = null;
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-term]');
    if (!link || !dialog || typeof dialog.showModal !== 'function' || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const template = document.getElementById(`term-preview-${link.dataset.term}`);
    if (!template) return;
    event.preventDefault();
    returnFocus = link;
    content.replaceChildren(template.content.cloneNode(true));
    dialog.showModal();
  });
  if (dialog) {
    dialog.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
      const rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
      content.replaceChildren();
      if (returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
    });
  }
  const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  document.querySelectorAll('[data-fresh-date]').forEach(status => {
    if (status.dataset.freshDate && status.dataset.freshDate < today) {
      status.textContent = '이전 자료 · 최신 업데이트 확인 필요';
      status.classList.add('is-stale');
    }
  });
  document.querySelectorAll('[data-live-policy-status]').forEach(status => {
    const container = status.closest('[data-opens]');
    if (!container) return;
    const {opens, deadline} = container.dataset;
    const label = deadline && deadline < today ? '마감' : opens && opens > today ? '접수 예정' : !opens || !deadline ? '기간 확인 필요' : deadline === today ? '마감일 당일 · 시각 확인' : '접수 기간 내 · 자격 확인';
    status.textContent = label;
    container.dataset.policyStatus = label;
  });
  document.querySelectorAll('[data-filter-scope]').forEach(scope => {
    const controls = scope.querySelector('.filter-controls');
    const list = scope.querySelector('[data-filter-list]');
    if (!controls || !list) return;
    controls.hidden = false;
    const input = controls.querySelector('[data-search-input]');
    const selects = [...controls.querySelectorAll('[data-filter-key]')];
    const cards = [...list.children].filter(card => card.hasAttribute('data-search'));
    function update() {
      const query = input.value.trim().toLocaleLowerCase('ko-KR');
      let count = 0;
      cards.forEach(card => {
        const matches = card.dataset.search.toLocaleLowerCase('ko-KR').includes(query) && selects.every(select => !select.value || card.dataset[select.dataset.filterKey] === select.value);
        card.hidden = !matches;
        if (matches) count += 1;
      });
      controls.querySelector('.filter-count').textContent = `${cards.length}개 중 ${count}개`;
      scope.querySelector('.filter-empty').hidden = count !== 0;
    }
    input.addEventListener('input', update);
    selects.forEach(select => select.addEventListener('change', update));
    update();
  });
})();
