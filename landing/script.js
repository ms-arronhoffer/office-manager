document.addEventListener('DOMContentLoaded', () => {
  const cfg = window.SITE_CONFIG || {};

  // ── Wire CTA links from config ─────────────────────────────────────────────
  document.querySelectorAll('[data-href]').forEach(el => {
    const key = el.getAttribute('data-href');
    const url = cfg[key];
    if (!url) return;
    if (el.tagName === 'A') {
      el.href = url;
    } else {
      el.addEventListener('click', () => { window.location.href = url; });
      el.style.cursor = 'pointer';
    }
  });

  // Wire demo mailto links
  document.querySelectorAll('[data-demo-email]').forEach(el => {
    const email = cfg.DEMO_EMAIL || '';
    const subject = encodeURIComponent('SwiftLease Demo Request');
    const body = encodeURIComponent('Hi,\n\nI\'d like to schedule a demo of SwiftLease.\n\nName:\nCompany:\nPhone:\n');
    if (el.tagName === 'A') el.href = `mailto:${email}?subject=${subject}&body=${body}`;
  });

  // Inject company name
  document.querySelectorAll('[data-company]').forEach(el => {
    el.textContent = cfg.COMPANY_NAME || 'SwiftLease';
  });

  // ── Sticky nav on scroll ───────────────────────────────────────────────────
  const nav = document.getElementById('main-nav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 40);
    }, { passive: true });
  }

  // ── Smooth scroll for anchor links ────────────────────────────────────────
  document.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', e => {
      const target = document.querySelector(link.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // ── Scroll-triggered reveal ────────────────────────────────────────────────
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -60px 0px' });

  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

  // ── Staggered card reveals ─────────────────────────────────────────────────
  const cardObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const cards = entry.target.querySelectorAll('.stagger-child');
        cards.forEach((card, i) => {
          setTimeout(() => card.classList.add('is-visible'), i * 80);
        });
        cardObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.05 });

  document.querySelectorAll('.stagger-parent').forEach(el => cardObserver.observe(el));

  // ── Animated counters ──────────────────────────────────────────────────────
  function animateCounter(el) {
    const target = parseInt(el.getAttribute('data-target'), 10);
    const duration = 1800;
    const start = performance.now();
    const suffix = el.getAttribute('data-suffix') || '';
    const prefix = el.getAttribute('data-prefix') || '';

    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = prefix + Math.floor(eased * target) + suffix;
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.querySelectorAll('[data-target]').forEach(animateCounter);
        counterObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  document.querySelectorAll('.stats-row').forEach(el => counterObserver.observe(el));

  // ── Pricing toggle (annual/monthly) ───────────────────────────────────────
  const toggle = document.getElementById('billing-toggle');
  if (toggle) {
    toggle.addEventListener('change', () => {
      const isAnnual = toggle.checked;
      document.querySelectorAll('.price-monthly').forEach(el => {
        el.style.display = isAnnual ? 'none' : 'block';
      });
      document.querySelectorAll('.price-annual').forEach(el => {
        el.style.display = isAnnual ? 'block' : 'none';
      });
      document.querySelectorAll('.billing-label').forEach((el, i) => {
        el.classList.toggle('active', isAnnual ? i === 1 : i === 0);
      });
    });
  }
});
