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

  const renderRowsInto = (target, rows) => {
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
  const renderRows = (targetId, rows) => renderRowsInto(byId(targetId), rows);

  const renderBreakdowns = (targetId, breakdowns) => {
    const target = byId(targetId);
    target.replaceChildren();
    breakdowns.forEach(breakdown => {
      const section = element('section', 'population-breakdown');
      section.append(element('h4', '', breakdown.label));
      const values = element('dl', 'key-values');
      renderRowsInto(values, breakdown.rows);
      section.append(values);
      target.append(section);
    });
  };

  const renderPopulation = (prefix, population) => {
    setText(`${prefix}-population-label`, population.label);
    setText(
      `${prefix}-population-count`,
      `${population.recorded} / ${population.denominator}`
    );
    renderRows(`${prefix}-population-values`, population.rows);
    renderBreakdowns(`${prefix}-population-breakdowns`, population.breakdowns);
  };

  const renderEligibility = (target, facts) => {
    target.replaceChildren();
    if (!facts.length) {
      target.append(element('li', 'none', 'No terminal eligibility facts.'));
      return;
    }
    facts.forEach(fact => {
      target.append(
        element('li', '', `${fact.label}: ${fact.value} · ${fact.reason || 'NONE'}`)
      );
    });
  };

  const caseEvidence = (title, rows) => {
    const section = element('section');
    section.append(element('h4', '', title));
    const values = element('dl', 'key-values');
    renderRowsInto(values, rows);
    section.append(values);
    return section;
  };

  const renderCaseStructure = structure => {
    const section = element('section', 'case-structure-evidence');
    section.append(element('h4', '', 'Frozen selected structure'));
    if (!structure.available) {
      section.append(element('p', 'none', 'Frozen structure evidence is unavailable.'));
      return section;
    }
    const summary = element('dl', 'key-values case-structure-summary');
    renderRowsInto(summary, structure.summary);
    section.append(summary);
    const legs = element('div', 'case-leg-grid');
    structure.legs.forEach(leg => {
      const card = element('article', 'case-leg-card');
      card.dataset.action = leg.action;
      card.append(
        element('span', 'leg-order', `LEG ${leg.position} · ${leg.role}`),
        element('h5', '', leg.label),
        element('p', 'instrument', leg.instrument_name)
      );
      const details = element('dl', 'key-values');
      renderRowsInto(details, leg.details);
      card.append(details);
      legs.append(card);
    });
    section.append(legs);
    return section;
  };

  const renderCase = (caseValue, index) => {
    const card = element('article', 'case-card');
    const heading = element('div', 'case-card-heading');
    const identity = element('div');
    identity.append(
      element('span', 'section-kicker', `CASE ${String(index + 1).padStart(2, '0')}`),
      element('h3', 'case-identity', caseValue.trade_case_id || 'UNKNOWN')
    );
    const state = caseValue.position_state !== 'UNKNOWN'
      ? caseValue.position_state
      : caseValue.entry_status;
    heading.append(identity, element('span', 'state-badge', state));
    card.append(heading, element('p', 'case-message', caseValue.message));

    const evidence = element('div', 'case-evidence-grid');
    evidence.append(
      caseEvidence('Case and Position', caseValue.facts),
      renderCaseStructure(
        caseValue.selected_structure || { available: false, summary: [], legs: [] }
      ),
      caseEvidence('Frozen Shadow Risk Allocation', caseValue.risk_allocation || []),
      caseEvidence('Entry causal evidence', caseValue.entry_evidence || []),
      caseEvidence('Entry economics', caseValue.entry_economics || []),
      caseEvidence('First immutable exit intent', caseValue.exit_intent),
      caseEvidence('Terminal Outcome', caseValue.outcome)
    );
    const eligibilitySection = element('section');
    eligibilitySection.append(element('h4', '', 'Eligibility'));
    const eligibility = element('ul', 'chip-list');
    renderEligibility(eligibility, caseValue.eligibility);
    eligibilitySection.append(eligibility);
    evidence.append(eligibilitySection);
    card.append(evidence);
    return card;
  };

  const renderCases = values => {
    const target = byId('case-list');
    target.replaceChildren();
    setText('case-count', String(values.length));
    if (!values.length) {
      target.append(
        element('p', 'empty-state', 'No TradeCase has been recorded for this target Session.')
      );
      return;
    }
    values.forEach((value, index) => target.append(renderCase(value, index)));
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
  const runtime = documentValue.runtime;
  const projection = documentValue.projection;
  setText('product-title', product.title);
  setText('strategy-name', product.strategy);
  setText('boundary-label', documentValue.boundary.label);
  setText('runtime-status', runtime.status);
  byId('runtime-status').dataset.tone = runtime.tone;
  setText('target-session-id', runtime.session_id);
  setText('session-id', snapshot.session_id);
  setText('observed-at', snapshot.observed_at);
  setText('runtime-updated-at', runtime.updated_at);
  setText('projection-state', projection.state);
  setText('projection-phase', projection.phase);
  byId('projection-state').dataset.tone = projection.tone;

  const boundaryList = byId('boundary-statements');
  boundaryList.replaceChildren();
  documentValue.boundary.statements.forEach(value => boundaryList.append(element('li', '', value)));

  setText('warning-count', String(documentValue.warnings.length));
  renderList('warning-list', documentValue.warnings, 'No snapshot warnings were reported.');
  renderList('blocker-list', projection.blockers, 'No projection blocker was reported.');
  renderRows('runtime-values', runtime.facts);
  renderPopulation('decision', documentValue.population.decisions);
  renderPopulation('outcome', documentValue.population.outcomes);
  renderRows('window-values', documentValue.window);
  renderRows('context-values', documentValue.context);
  renderRows('methodology-values', documentValue.methodology);
  renderStructure(documentValue.structure);
  renderCases(documentValue.cases);

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
