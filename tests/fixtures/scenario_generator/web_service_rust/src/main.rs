//! Tiny actix-web fixture for the web_service_rust discoverer.

use actix_web::{get, post, delete, web, App, HttpServer, Responder};

/// List all items.
#[get("/items")]
async fn list_items() -> impl Responder {
    "[]"
}

/// Create a new item and return its id.
#[post("/items")]
async fn create_item() -> impl Responder {
    "{\"id\": 1}"
}

/// Delete an item by id.
#[delete("/items/{id}")]
async fn delete_item(_path: web::Path<u32>) -> impl Responder {
    ""
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    HttpServer::new(|| {
        App::new()
            .service(list_items)
            .service(create_item)
            .service(delete_item)
    })
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
