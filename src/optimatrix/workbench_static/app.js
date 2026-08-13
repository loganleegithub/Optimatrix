(() => {
  'use strict';

  const documentValue = window.OPTIMATRIX_WORKBENCH;
  if (!documentValue || documentValue.schema_version !== 2) {
    document.body.textContent = 'Unsupported or missing Workbench export.';
    return;
  }

  const byId = id => document.getElementById(id);
  const setText = (id, value) => { byId(id).textContent = value || '—'; };
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const renderList = (targetId, values, emptyText) => {
    const target = byId(targetId);
    target.replaceChildren();
    if (!values.length) {
      const item = element('li', 'none', emptyText);
      target.append(item);
      return;
    }
    values.forEach(value => {
      const item = element('li', '', value.code);
      if (value.tone) item.dataset.tone = value.tone;
      target.append(item);
    });
  };

  const renderRows = (targetId, rows) => {
    const target = byId(targetId);
    target.replaceChildren();
    if (!rows.length) {
      const wrapper = element('div');
      wrapper.append(element('dt', '', 'Availability'), element('dd', '', 'UNKNOWN'));
      target.append(wrapper);
      return;
    }
    rows.forEach(row => {
      const wrapper = element('div');
      wrapper.append(element('dt', '', row.label), element('dd', '', row.value));
      target.append(wrapper);
    });
  };

  const renderLeg = leg => {
    const card = element('article', 'leg-card');
    card.dataset.action = leg.action;
    card.append(
      element('span', 'leg-order', `LEG ${leg.position} · ${leg.action} ${leg.option_type}`),
      element('h3', '', leg.label),
      element('p', 'instrument', leg.instrument_name)
    );
    const details = element('dl');
    leg.details.forEach(row => {
      const wrapper = element('div');
      wrapper.append(element('dt', '', row.label), element('dd', '', row.value));
      details.append(wrapper);
    });
    if (!leg.quote_available) {
      const wrapper = element('div');
      wrapper.append(element('dt', '', 'Public quote'), element('dd', '', 'UNAVAILABLE'));
      details.append(wrapper);
    }
    card.append(details);
    return card;
  };

  const renderStructure = structure => {
    setText('structure-kind', structure.kind);
    setText('structure-message', structure.message);
    const kind = byId('structure-kind');
    kind.dataset.tone = structure.available ? 'positive' : 'warning';
    const empty = byId('structure-empty');
    const grid = byId('leg-grid');
    grid.replaceChildren();
    empty.hidden = structure.available;
    if (structure.available) {
      structure.legs.forEach(leg => grid.append(renderLeg(leg)));
    } else {
      empty.textContent = structure.message;
    }
    renderRows('structure-metrics', structure.metrics);
  };

  const product = documentValue.product;
  const snapshot = documentValue.snapshot;
  const projection = documentValue.projection;
  setText('product-title', product.title);
  setText('strategy-name', product.strategy);
  setText('boundary-label', documentValue.boundary.label);
  setText('session-id', snapshot.session_id);
  setText('observed-at', snapshot.observed_at);
  setText('projection-state', projection.state);
  setText('projection-phase', projection.phase);
  byId('projection-state').dataset.tone = projection.tone;

  const boundaryList = byId('boundary-statements');
  boundaryList.replaceChildren();
  documentValue.boundary.statements.forEach(value => boundaryList.append(element('li', '', value)));

  setText('warning-count', String(documentValue.warnings.length));
  renderList('warning-list', documentValue.warnings, 'No snapshot warnings were reported.');
  renderList('blocker-list', projection.blockers, 'No projection blocker was reported.');
  renderRows('window-values', documentValue.window);
  renderRows('context-values', documentValue.context);
  renderRows('methodology-values', documentValue.methodology);
  renderStructure(documentValue.structure);
  const caseValue = documentValue.case;
  setText('case-message', caseValue.message);
  renderRows('case-facts', caseValue.facts);
  renderRows('case-exit-intent', caseValue.exit_intent);
  renderRows('case-outcome', caseValue.outcome);
  const eligibility = byId('case-eligibility');
  eligibility.replaceChildren();
  if (!caseValue.eligibility.length) {
    eligibility.append(element('li', 'none', 'No terminal eligibility facts.'));
  } else {
    caseValue.eligibility.forEach(fact => {
      eligibility.append(element('li', '', `${fact.label}: ${fact.value} · ${fact.reason}`));
    });
  }

  document.querySelectorAll('[data-theme]').forEach(button => {
    button.addEventListener('click', () => {
      const theme = button.dataset.theme;
      document.documentElement.dataset.theme = theme;
      document.querySelectorAll('[data-theme]').forEach(candidate => {
        candidate.setAttribute('aria-pressed', String(candidate === button));
      });
    });
  });
})();
