package controllers

import (
	"context"

	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

// WidgetReconciler reconciles a Widget object.
type WidgetReconciler struct {
	Client any
	Scheme any
}

// Reconcile is the entry point invoked by controller-runtime when a
// Widget changes.
func (r *WidgetReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	_ = log.FromContext(ctx)
	_ = controllerutil.SetControllerReference
	return ctrl.Result{}, nil
}

// GadgetReconciler reconciles a Gadget object — a second resource handled
// by the same operator.
type GadgetReconciler struct {
	Client any
	Scheme any
}

func (r *GadgetReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	_ = log.FromContext(ctx)
	_ = controllerutil.SetControllerReference
	return ctrl.Result{}, nil
}
