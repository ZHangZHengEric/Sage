import React, { useState, useEffect } from 'react';
import { X, Plus, ArrowRight, Edit, Trash2, Save, GripVertical } from 'lucide-react';
import './WorkflowEditModal.css';
import { useLanguage } from '../contexts/LanguageContext';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import {
  useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

// 可拖拽的步骤组件
const SortableStepItem = ({ step, index, updateStep, removeStep, canRemove, t }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`workflow-step-item ${isDragging ? 'dragging' : ''}`}
      {...attributes}
    >
      <div className="step-number">{index + 1}</div>
      <div className="step-content">
        <div className="drag-handle" {...listeners}>
          <GripVertical size={16} />
        </div>
        <input
          type="text"
          className="input step-input"
          placeholder={t('agentEdit.stepPlaceholder')}
          value={step.content}
          onChange={(e) => updateStep(index, e.target.value)}
        />
        {canRemove && (
          <button
            className="remove-btn"
            onClick={() => removeStep(index)}
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
    </div>
  );
};

const WorkflowEditModal = ({ isOpen, workflow, onSave, onClose }) => {
  const { t } = useLanguage();
  const [workflowData, setWorkflowData] = useState({
    key: '',
    steps: [{ id: 'step-0', content: '' }]
  });

  // 拖拽传感器配置
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  useEffect(() => {
    if (workflow) {
      const steps = workflow.steps && workflow.steps.length > 0 
        ? workflow.steps.map((step, index) => ({
            id: `step-${index}`,
            content: typeof step === 'string' ? step : step.content || ''
          }))
        : [{ id: 'step-0', content: '' }];
      
      setWorkflowData({
        key: workflow.key || '',
        steps: steps
      });
    } else {
      setWorkflowData({
        key: '',
        steps: [{ id: 'step-0', content: '' }]
      });
    }
  }, [workflow]);

  const addStep = () => {
    setWorkflowData(prev => ({
      ...prev,
      steps: [...prev.steps, { id: `step-${Date.now()}`, content: '' }]
    }));
  };

  const removeStep = (index) => {
    if (workflowData.steps.length > 1) {
      setWorkflowData(prev => ({
        ...prev,
        steps: prev.steps.filter((_, i) => i !== index)
      }));
    }
  };

  const updateStep = (index, value) => {
    setWorkflowData(prev => ({
      ...prev,
      steps: prev.steps.map((step, i) => i === index ? { ...step, content: value } : step)
    }));
  };

  const updateWorkflowName = (value) => {
    setWorkflowData(prev => ({
      ...prev,
      key: value
    }));
  };

  // 拖拽结束处理函数
  const handleDragEnd = (event) => {
    const { active, over } = event;

    if (active.id !== over?.id && over) {
      const activeIndex = workflowData.steps.findIndex(step => step.id === active.id);
      const overIndex = workflowData.steps.findIndex(step => step.id === over.id);

      if (activeIndex !== -1 && overIndex !== -1) {
        setWorkflowData(prev => ({
          ...prev,
          steps: arrayMove(prev.steps, activeIndex, overIndex)
        }));
      }
    }
  };

  const handleSave = () => {
    console.log('[DEBUG] WorkflowEditModal handleSave - workflowData:', workflowData);
    if (workflowData.key.trim() && workflowData.steps.some(step => step.content.trim())) {
      const saveData = {
        key: workflowData.key,
        name: workflowData.key, // 为了兼容性，同时提供key和name
        steps: workflowData.steps.map(step => step.content)
      };
      console.log('[DEBUG] WorkflowEditModal handleSave - saveData:', saveData);
      onSave(saveData);
      onClose();
    } else {
      console.log('[DEBUG] WorkflowEditModal handleSave - 验证失败:', {
        keyTrimmed: workflowData.key.trim(),
        hasValidSteps: workflowData.steps.some(step => step.content.trim()),
        steps: workflowData.steps
      });
    }
  };

  if (!isOpen) return null;

  return (
    <div className="workflow-modal-overlay">
      <div className="workflow-modal">
        <div className="workflow-modal-header">
          <h3>{workflow ? t('agentEdit.editWorkflow') : t('agentEdit.createWorkflow')}</h3>
          <button className="btn btn-ghost btn-xs" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="workflow-modal-content">
          <div className="workflow-name-section">
            <label className="form-label">{t('agentEdit.workflowName')}</label>
            <input
              type="text"
              className="input"
              placeholder={t('agentEdit.workflowNamePlaceholder')}
              value={workflowData.key}
              onChange={(e) => updateWorkflowName(e.target.value)}
            />
          </div>

          <div className="workflow-steps-section">
            <div className="steps-header">
              <label className="form-label">{t('agentEdit.workflowSteps')}</label>
              <button className="btn btn-secondary btn-sm" onClick={addStep}>
                <Plus size={14} />
                {t('agentEdit.addStep')}
              </button>
            </div>

            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <div className="workflow-diagram">
                <SortableContext
                  items={workflowData.steps.map(step => step.id)}
                  strategy={verticalListSortingStrategy}
                >
                  {workflowData.steps.map((step, index) => (
                    <SortableStepItem
                      key={step.id}
                      step={step}
                      index={index}
                      updateStep={updateStep}
                      removeStep={removeStep}
                      canRemove={workflowData.steps.length > 1}
                      t={t}
                    />
                  ))}
                </SortableContext>
              </div>
            </DndContext>
          </div>
        </div>

        <div className="workflow-modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleSave}
            disabled={!workflowData.key.trim() || !workflowData.steps.some(step => step.content.trim())}
          >
            <Save size={16} />
            {t('common.save')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default WorkflowEditModal;