import asyncio
import json

from mcp.server.fastmcp import FastMCP

# Import from supermarkets package
from src.supermarkets import catalog, resolve
from src.supermarkets import (
    coles_search_products,
    coles_extract_products,
    COLES_DEFAULT_STORE_ID,
    woolworths_search_products,
)

# Initialize FastMCP server
mcp = FastMCP("supermarket-mcp", host="localhost", port=7860)


@mcp.tool()
async def get_coles_products(query: str, store_id: str = COLES_DEFAULT_STORE_ID, limit: int = 10) -> str:
    """Search for products at Coles.

    Args:
        query: The product search query.
        store_id: The Coles store ID to search in.
        limit: Maximum number of products to return.
    """
    try:
        # The limit parameter in coles_search_products's signature is not used in its API call.
        # We will fetch all available (up to API's own limit) and then slice.
        # Also, the original coles_search_products signature includes a limit, but it's not used.
        # Forcing keyword arguments for clarity with asyncio.to_thread
        search_results = await asyncio.to_thread(
            coles_search_products,
            query=query,
            store_id=store_id
            # limit parameter is not passed here as the underlying coles_search_products doesn't use it in API call
        )

        if search_results.get("status") == "error":
            return f"Error fetching Coles products: {search_results.get('message', 'Unknown error')}\nResponse: {search_results.get('response_text', '')}"

        # extract_products is CPU-bound/quick, but run in thread for consistency with I/O
        products = await asyncio.to_thread(coles_extract_products, search_results)

        # Apply limit after extraction
        products = products[: min(limit, len(products))]

        if not products:
            return f"No products found at Coles for '{query}'."

        formatted_products = []
        for p in products:
            price_str = f"${p['price']:.2f}" if p['price'] is not None else "N/A"
            unit_str = p['unit'] if p['unit'] else "N/A" # Ensure unit is not None
            formatted_products.append(
                f"Name: {p['name']}\nPrice: {price_str}\nUnit: {unit_str}\nStore: {p['store']}"
            )
        return "\n---\n".join(formatted_products)
    except Exception as e:
        return f"An unexpected error occurred in get_coles_products: {str(e)}"


@mcp.tool()
async def get_woolworths_products(query: str, limit: int = 10) -> str:
    """Search for products at Woolworths.

    Args:
        query: The product search query.
        limit: Maximum number of products to return.
    """
    try:
        search_results = await asyncio.to_thread(woolworths_search_products, query=query)

        if search_results.get("status") == "error":
            return f"Error fetching Woolworths products: {search_results.get('message', 'Unknown error')}\nResponse: {search_results.get('response_text', '')}"

        products = search_results.get("products", [])

        # Apply limit after fetching
        products = products[: min(limit, len(products))]

        if not products:
            return f"No products found at Woolworths for '{query}'."

        formatted_products = []
        for p in products:
            price_str = f"${p['price']:.2f}" if p['price'] is not None else "N/A"
            unit_str = p['unit'] if p['unit'] else "N/A" # Ensure unit is not None
            formatted_products.append(
                f"Name: {p['name']}\nPrice: {price_str}\nUnit: {unit_str}\nStore: {p['store']}"
            )
        return "\n---\n".join(formatted_products)
    except Exception as e:
        return f"An unexpected error occurred in get_woolworths_products: {str(e)}"


@mcp.tool()
async def search_woolworths(query: str, limit: int = 10) -> str:
    """Search Woolworths and return structured JSON, including pack size in
    grams and the price per kilogram.

    Prefer this over get_woolworths_products for anything that does arithmetic:
    it keeps the pack magnitude and derives the pack price from the store's own
    per-unit price, so variable-weight lines (priced per kg but sold as a
    ~350g fillet) are costed correctly.

    Args:
        query: The product search query.
        limit: Maximum number of products to return.
    """
    result = await asyncio.to_thread(catalog.search, query=query, limit=limit)
    return json.dumps(result, indent=2)


@mcp.tool()
async def price_planned_food(
    food: str,
    query: str = "",
    pack_grams: float = 0,
) -> str:
    """Price one planned food on the meal plan's own basis.

    Chooses the listing whose pack is closest to the one the plan buys, and
    keeps a drained weight drained, so the returned price/pack pair stays
    comparable with what the plan already recorded. The result carries a
    confidence score and a needs_review flag -- do not overwrite a hand-checked
    figure when needs_review is set.

    Args:
        food: The planned food name, e.g. "Woolworths Chickpeas, drained".
        query: Store search term. Defaults to the food name.
        pack_grams: The pack size the plan buys, in grams. 0 if unknown.
    """
    result = await asyncio.to_thread(
        resolve.resolve_food,
        food=food,
        query=query or food,
        target_pack_g=pack_grams or None,
    )
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="stdio")