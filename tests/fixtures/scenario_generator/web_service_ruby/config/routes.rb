# Tiny Rails routes fixture exercising the DSL forms the web_service_ruby
# discoverer must handle:
#   1. get "/path", to: "controller#action" — verb with `to:` target.
#   2. post "/path", to: "..."             — verb with a doc comment above.
#   3. resources :name                     — RESTful collection.
Rails.application.routes.draw do
  # List every widget currently in the inventory.
  get "/widgets", to: "widgets#index"

  # Create a new widget from the request body.
  post "/widgets", to: "widgets#create"

  # Standard RESTful resource for users.
  resources :users
end
