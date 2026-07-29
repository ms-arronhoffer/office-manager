import type { WizardProps } from '@cloudscape-design/components/wizard';

/**
 * Shared i18nStrings for the Cloudscape {@link Wizard} component so every guided
 * flow (office onboarding, lease onboarding, …) presents identical navigation
 * labels. `submitButton` is overridable per-wizard where a more specific verb is
 * helpful (e.g. "Create office").
 */
export function wizardI18nStrings(submitLabel = 'Submit'): WizardProps.I18nStrings {
  return {
    stepNumberLabel: (stepNumber) => `Step ${stepNumber}`,
    collapsedStepsLabel: (stepNumber, stepsCount) => `Step ${stepNumber} of ${stepsCount}`,
    skipToButtonLabel: (step) => `Skip to ${step.title}`,
    navigationAriaLabel: 'Steps',
    cancelButton: 'Cancel',
    previousButton: 'Previous',
    nextButton: 'Next',
    submitButton: submitLabel,
    optional: 'optional',
  };
}
