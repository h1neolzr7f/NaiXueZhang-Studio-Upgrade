(function () {
  'use strict';

  let rootEl = null;
  let observer = null;
  const cardThumbs = new WeakMap();

  function loadCard(card) {
    if (!card) return;
    const thumbUrl = cardThumbs.get(card);
    const img = card.querySelector && card.querySelector('img');
    if (!img || !thumbUrl || img.src) return;
    img.src = thumbUrl;
  }

  function unloadCard(card) {
    if (!card) return;
    const img = card.querySelector && card.querySelector('img');
    if (!img || !img.src) return;
    img.removeAttribute('src');
  }

  function getObserver() {
    if (!('IntersectionObserver' in window)) return null;
    if (observer) return observer;
    observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const card = entry.target;
        if (entry.isIntersecting) {
          loadCard(card);
          return;
        }
        const top = entry.boundingClientRect.top;
        const bottom = entry.boundingClientRect.bottom;
        const band = window.innerHeight * 3;
        if (top > band || bottom < -band) unloadCard(card);
      });
    }, {
      root: null,
      rootMargin: '800px 0px',
      threshold: 0.01,
    });
    return observer;
  }

  function init(galleryEl) {
    rootEl = galleryEl || rootEl || document.getElementById('gallery');
    return !!rootEl;
  }

  function observeCard(card, thumbUrl, eagerThumb) {
    if (!card) return;
    if (thumbUrl) cardThumbs.set(card, String(thumbUrl));
    if (eagerThumb) {
      const img = card.querySelector && card.querySelector('img');
      if (img && !img.src && thumbUrl) img.src = String(thumbUrl);
    }
    const io = getObserver();
    if (!io) {
      loadCard(card);
      return;
    }
    io.observe(card);
  }

  window.GalleryVirtual = {
    init,
    observeCard,
    loadCard,
    unloadCard,
  };
})();
