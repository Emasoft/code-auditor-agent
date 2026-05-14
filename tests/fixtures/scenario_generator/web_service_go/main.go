// Tiny Go fixture exercising the route-registration forms the
// web_service_go discoverer must handle:
//  1. r.GET("/path", handler) on a *gin.Engine — ALL-CAPS verb method.
//  2. r.POST(...) with a leading doc comment.
//  3. http.HandleFunc on the net/http stdlib mux — method-agnostic.
package main

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	// List every widget currently in the inventory.
	r.GET("/widgets", listWidgets)

	// Create a new widget from the request body.
	r.POST("/widgets", createWidget)

	// Stdlib-style fallback health probe.
	http.HandleFunc("/healthz", healthz)

	r.Run(":8080")
}

func listWidgets(c *gin.Context) {
	c.JSON(200, gin.H{"widgets": []string{}})
}

func createWidget(c *gin.Context) {
	c.JSON(201, gin.H{"id": 1})
}

func healthz(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(200)
	_, _ = w.Write([]byte("ok"))
}
