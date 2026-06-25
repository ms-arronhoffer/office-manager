import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Select from '@cloudscape-design/components/select';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Spinner from '@cloudscape-design/components/spinner';
import Textarea from '@cloudscape-design/components/textarea';
import Tiles from '@cloudscape-design/components/tiles';
import Alert from '@cloudscape-design/components/alert';
import Table from '@cloudscape-design/components/table';
import client from '@/api/client';
import {
  wizardConfigs as wizardApi,
  offices as officesApi,
  ticketCategories as categoriesApi,
  maintenanceTickets as ticketsApi,
} from '@/api';
import { useAuth } from '@/auth/AuthContext';
import type { WizardStep, WizardOption, Office, TicketCategory } from '@/types';

interface ChatMessage {
  role: 'bot' | 'user';
  content: string;
}

type SelectOption = { label: string; value: string };

const TicketPortalPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [steps, setSteps] = useState<WizardStep[]>([]);
  const [currentStepId, setCurrentStepId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [createdTicketId, setCreatedTicketId] = useState<string | null>(null);

  // Dynamic data for office/category selects
  const [officeOptions, setOfficeOptions] = useState<SelectOption[]>([]);
  const [categoryOptions, setCategoryOptions] = useState<SelectOption[]>([]);

  // Input state for text steps
  const [textInput, setTextInput] = useState('');
  // Input state for select steps
  const [selectValue, setSelectValue] = useState<SelectOption | null>(null);
  // Input state for choice/tiles steps
  const [tileValue, setTileValue] = useState<string | null>(null);

  // State for display_results steps
  const [displayResults, setDisplayResults] = useState<Record<string, unknown>[] | null>(null);
  const [displayLoading, setDisplayLoading] = useState(false);

  // Scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, currentStepId]);

  // Load wizard config + reference data
  useEffect(() => {
    const init = async () => {
      try {
        const [configRes, officesRes, categoriesRes] = await Promise.all([
          wizardApi.getActive(),
          officesApi.list({ page_size: 1000 }),
          categoriesApi.list(),
        ]);

        const config = configRes.data;
        setSteps(config.steps);

        const offices: Office[] = 'items' in officesRes.data
          ? (officesRes.data as { items: Office[] }).items
          : officesRes.data as unknown as Office[];
        setOfficeOptions(
          offices
            .filter((o) => o.is_active)
            .map((o) => ({ label: o.location_name, value: o.id }))
        );

        const categories: TicketCategory[] = categoriesRes.data as unknown as TicketCategory[];
        setCategoryOptions(
          categories.map((c) => ({ label: c.name, value: c.id }))
        );

        // Start from first step
        if (config.steps.length > 0) {
          setCurrentStepId(config.steps[0].id);
        }
      } catch {
        setError('Failed to load ticket wizard configuration.');
      } finally {
        setLoading(false);
      }
    };
    init();
  }, []);

  const currentStep = steps.find((s) => s.id === currentStepId) ?? null;

  const addBotMessage = useCallback((text: string) => {
    setChatHistory((prev) => [...prev, { role: 'bot', content: text }]);
  }, []);

  const addUserMessage = useCallback((text: string) => {
    setChatHistory((prev) => [...prev, { role: 'user', content: text }]);
  }, []);

  // Auto-advance for message steps
  useEffect(() => {
    if (!currentStep || currentStep.type !== 'message') return;
    addBotMessage(currentStep.text);
    const timer = setTimeout(() => {
      if (currentStep.next) {
        setCurrentStepId(currentStep.next);
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [currentStepId, currentStep, addBotMessage]);

  // Add bot prompt for interactive steps
  useEffect(() => {
    if (!currentStep) return;
    if (currentStep.type === 'message') return; // handled above
    if (currentStep.type === 'display_results') return; // handled below
    if (currentStep.type !== 'confirm') {
      addBotMessage(currentStep.text);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepId]);

  // Fetch data for display_results steps
  useEffect(() => {
    if (!currentStep || currentStep.type !== 'display_results') return;
    addBotMessage(currentStep.text);

    const fetchResults = async () => {
      setDisplayLoading(true);
      setDisplayResults(null);
      try {
        let url = currentStep.endpoint ?? '';
        (currentStep.params_from ?? []).forEach((param) => {
          url = url.replace(`{${param}}`, answers[param] ?? '');
        });
        const res = await client.get(url);
        const data = Array.isArray(res.data) ? res.data : (res.data as { items?: unknown[] }).items ?? [];
        setDisplayResults(data as Record<string, unknown>[]);
      } catch {
        setError('Failed to load results.');
      } finally {
        setDisplayLoading(false);
      }
    };
    fetchResults();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepId]);

  const resolveOptions = (step: WizardStep): SelectOption[] => {
    if (!step.options) return [];
    if (step.options === '__offices__') return officeOptions;
    if (step.options === '__categories__') return categoryOptions;
    if (Array.isArray(step.options)) {
      return step.options.map((o: WizardOption) => ({ label: o.label, value: o.value }));
    }
    return [];
  };

  const advanceToNext = (step: WizardStep, selectedValue?: string) => {
    // For choice steps, the next may be per-option
    if (step.type === 'choice' && selectedValue && Array.isArray(step.options)) {
      const option = (step.options as WizardOption[]).find((o) => o.value === selectedValue);
      if (option?.next) {
        setCurrentStepId(option.next);
        return;
      }
    }
    if (step.next) {
      setCurrentStepId(step.next);
    }
  };

  const handleTextSubmit = () => {
    if (!currentStep || !textInput.trim()) return;
    const value = textInput.trim();

    // Handle optional fields with "skip"
    if (currentStep.optional && value.toLowerCase() === 'skip') {
      addUserMessage('(skipped)');
      setTextInput('');
      advanceToNext(currentStep);
      return;
    }

    if (currentStep.field) {
      setAnswers((prev) => ({ ...prev, [currentStep.field!]: value }));
    }
    addUserMessage(value);
    setTextInput('');
    advanceToNext(currentStep);
  };

  const handleSelectSubmit = () => {
    if (!currentStep || !selectValue) return;
    if (currentStep.field) {
      setAnswers((prev) => ({ ...prev, [currentStep.field!]: selectValue.value }));
    }
    addUserMessage(selectValue.label);
    setSelectValue(null);
    advanceToNext(currentStep, selectValue.value);
  };

  const handleTileSelect = (value: string) => {
    if (!currentStep) return;
    const options = resolveOptions(currentStep);
    const selected = options.find((o) => o.value === value);
    if (currentStep.field) {
      setAnswers((prev) => ({ ...prev, [currentStep.field!]: value }));
    }
    addUserMessage(selected?.label ?? value);
    setTileValue(null);
    advanceToNext(currentStep, value);
  };

  const handleSubmitTicket = async () => {
    setSubmitting(true);
    try {
      const payload = {
        subject: answers.subject || 'Maintenance Request',
        description: answers.description || '',
        priority: answers.priority || 'medium',
        office_id: answers.office_id || '',
        category_id: answers.category_id || '',
        location_hours: answers.location_hours || undefined,
      };
      const res = await ticketsApi.create(payload);
      setCreatedTicketId(res.data.id);
      setSubmitted(true);
      addBotMessage('Your ticket has been submitted successfully!');
    } catch {
      setError('Failed to submit ticket. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmAction = async () => {
    // Only submit a ticket if the required ticket fields were collected
    if (answers.subject && answers.office_id && answers.category_id) {
      await handleSubmitTicket();
    } else {
      setSubmitted(true);
      addBotMessage('Done! Your request has been processed.');
    }
  };

  const handleStartOver = () => {
    setAnswers({});
    setChatHistory([]);
    setCurrentStepId(steps.length > 0 ? steps[0].id : null);
    setTextInput('');
    setSelectValue(null);
    setTileValue(null);
    setSubmitted(false);
    setCreatedTicketId(null);
    setDisplayResults(null);
    setDisplayLoading(false);
    setError(null);
  };

  const getFieldLabel = (field: string): string => {
    const labels: Record<string, string> = {
      office_id: 'Office',
      category_id: 'Category',
      subject: 'Subject',
      description: 'Description',
      priority: 'Priority',
      location_hours: 'Location Hours',
    };
    return labels[field] || field;
  };

  const getDisplayValue = (field: string, value: string): string => {
    if (field === 'office_id') {
      return officeOptions.find((o) => o.value === value)?.label ?? value;
    }
    if (field === 'category_id') {
      return categoryOptions.find((o) => o.value === value)?.label ?? value;
    }
    return value;
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: '#f2f3f3' }}>
        <Spinner size="large" />
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f2f3f3', display: 'flex', flexDirection: 'column' }}>
      {/* Top bar */}
      <div style={{ background: '#0f1b2a', color: '#fff', padding: '12px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box variant="h3" color="inherit">SwiftLease Portal</Box>
        <SpaceBetween direction="horizontal" size="xs">
          <Box color="inherit">{user?.display_name}</Box>
          <Button variant="link" onClick={logout}>
            Sign out
          </Button>
        </SpaceBetween>
      </div>

      {/* Chat area */}
      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', padding: '24px 16px', overflow: 'auto' }}>
        <div style={{ width: '100%', maxWidth: 640 }}>
          <Container
            header={<Header variant="h2">What would you like to do?</Header>}
          >
            <SpaceBetween size="m">
              {error && (
                <Alert type="error" dismissible onDismiss={() => setError(null)}>
                  {error}
                </Alert>
              )}

              {/* Chat messages */}
              <div style={{ maxHeight: 400, overflowY: 'auto', padding: '8px 0' }}>
                <SpaceBetween size="s">
                  {chatHistory.map((msg, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      <div
                        style={{
                          background: msg.role === 'user' ? '#0972d3' : '#e9ebed',
                          color: msg.role === 'user' ? '#fff' : '#000716',
                          padding: '8px 14px',
                          borderRadius: 12,
                          maxWidth: '80%',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </SpaceBetween>
              </div>

              {/* Current step input */}
              {!submitted && currentStep && currentStep.type === 'text' && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <Textarea
                      value={textInput}
                      onChange={({ detail }) => setTextInput(detail.value)}
                      placeholder={currentStep.optional ? 'Type your answer or "skip"...' : 'Type your answer...'}
                      rows={2}
                    />
                  </div>
                  <Button
                    variant="primary"
                    onClick={handleTextSubmit}
                    disabled={!textInput.trim()}
                    iconName="send"
                  >
                    Send
                  </Button>
                </div>
              )}

              {!submitted && currentStep && currentStep.type === 'select' && (
                <div style={{ display: 'flex', gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <Select
                      selectedOption={selectValue}
                      onChange={({ detail }) =>
                        setSelectValue(detail.selectedOption as SelectOption)
                      }
                      options={resolveOptions(currentStep)}
                      placeholder="Select an option..."
                      filteringType="auto"
                    />
                  </div>
                  <Button
                    variant="primary"
                    onClick={handleSelectSubmit}
                    disabled={!selectValue}
                  >
                    Select
                  </Button>
                </div>
              )}

              {!submitted && currentStep && currentStep.type === 'choice' && (
                <Tiles
                  value={tileValue ?? ''}
                  onChange={({ detail }) => handleTileSelect(detail.value)}
                  items={resolveOptions(currentStep).map((o) => ({
                    label: o.label,
                    value: o.value,
                  }))}
                  columns={2}
                />
              )}

              {!submitted && currentStep && currentStep.type === 'confirm' && (
                <SpaceBetween size="m">
                  <Box variant="h4">{currentStep.text}</Box>
                  <Container>
                    <SpaceBetween size="xs">
                      {Object.entries(answers)
                        .filter(([field]) => !field.startsWith('_'))
                        .map(([field, value]) => (
                        <div key={field} style={{ display: 'flex', gap: 8 }}>
                          <Box variant="awsui-key-label">{getFieldLabel(field)}:</Box>
                          <Box>{getDisplayValue(field, value)}</Box>
                        </div>
                      ))}
                    </SpaceBetween>
                  </Container>
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={handleStartOver}>Start Over</Button>
                    <Button
                      variant="primary"
                      onClick={handleConfirmAction}
                      loading={submitting}
                    >
                      {answers.subject && answers.office_id && answers.category_id ? 'Submit Ticket' : 'Done'}
                    </Button>
                  </SpaceBetween>
                </SpaceBetween>
              )}

              {!submitted && currentStep && currentStep.type === 'guidance' && (
                <SpaceBetween size="m">
                  <Alert type="info">
                    {currentStep.text}
                  </Alert>
                  {currentStep.followUp && (
                    <Box color="text-body-secondary">{currentStep.followUp}</Box>
                  )}
                  <Button onClick={handleStartOver}>Start Over</Button>
                </SpaceBetween>
              )}

              {!submitted && currentStep && currentStep.type === 'display_results' && (
                <SpaceBetween size="m">
                  {displayLoading ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '16px 0' }}>
                      <Spinner size="large" />
                    </div>
                  ) : displayResults && displayResults.length > 0 ? (
                    <Table
                      items={displayResults}
                      columnDefinitions={(currentStep.columns ?? []).map((col) => ({
                        id: col.key,
                        header: col.header,
                        cell: (item: Record<string, unknown>) => {
                          const val = item[col.key];
                          if (val === null || val === undefined) return '\u2014';
                          if (typeof val === 'boolean') return val ? 'Yes' : 'No';
                          return String(val);
                        },
                      }))}
                      variant="embedded"
                      empty={
                        <Box textAlign="center" color="inherit">
                          No results found.
                        </Box>
                      }
                    />
                  ) : (
                    <Alert type="info">No results found for this office.</Alert>
                  )}
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={handleStartOver}>Start Over</Button>
                    {currentStep.next && (
                      <Button variant="primary" onClick={() => advanceToNext(currentStep)}>
                        Continue
                      </Button>
                    )}
                  </SpaceBetween>
                </SpaceBetween>
              )}

              {submitted && (
                <SpaceBetween size="m">
                  <Alert type="success">
                    {createdTicketId
                      ? 'Your maintenance request has been submitted successfully.'
                      : 'Done!'}
                  </Alert>
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button onClick={handleStartOver}>Start Over</Button>
                    {createdTicketId && user?.role !== 'ticketer' && (
                      <Button
                        variant="primary"
                        onClick={() => navigate(`/maintenance-tickets/${createdTicketId}`)}
                      >
                        View Ticket
                      </Button>
                    )}
                  </SpaceBetween>
                </SpaceBetween>
              )}
            </SpaceBetween>
          </Container>
        </div>
      </div>
    </div>
  );
};

export default TicketPortalPage;
