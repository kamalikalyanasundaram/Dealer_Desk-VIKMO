import Product3DViewer from './Product3DViewer'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  Boxes,
  Building2,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  ClipboardList,
  Clock3,
  Eye,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  Package,
  PackageCheck,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  ShoppingCart,
  SlidersHorizontal,
  Truck,
  Warehouse,
  X,
} from 'lucide-react'

const NAVIGATION = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'products', label: 'Products', icon: Boxes },
  { id: 'inventory', label: 'Inventory', icon: Warehouse },
  { id: 'dealers', label: 'Dealers', icon: Building2 },
  { id: 'orders', label: 'Orders', icon: ClipboardList },
]

const PAGE_SIZE = 20

class ApiError extends Error {
  constructor(message, code, details = []) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details
  }
}

async function apiRequest(path, { method = 'GET', body, headers = {}, signal } = {}) {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  let payload
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const error = payload?.error
    throw new ApiError(
      error?.message || `Request failed (${response.status}).`,
      error?.code || 'REQUEST_FAILED',
      error?.details || [],
    )
  }
  return payload
}

async function getAllPages(path, signal) {
  const rows = []
  let page = 1
  let expectedCount = Infinity
  while (rows.length < expectedCount) {
    const separator = path.includes('?') ? '&' : '?'
    const result = await apiRequest(`${path}${separator}page=${page}&page_size=100`, { signal })
    if (!Array.isArray(result?.results)) {
      throw new ApiError('The server returned an unexpected list response.', 'BAD_RESPONSE')
    }
    rows.push(...result.results)
    expectedCount = result.count
    if (result.next === null || result.next === undefined || result.results.length === 0) break
    page += 1
  }
  return rows
}

function money(value) {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(amount)
}

function initials(name = '') {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('') || '—'
}

function shortDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

function shortTime(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function statusLabel(status) {
  return (status || '').toLowerCase().replaceAll('_', ' ')
}

function StatusBadge({ status }) {
  return <span className={`status-badge status-${(status || 'unknown').toLowerCase()}`}>{statusLabel(status)}</span>
}

function LoadingState({ label = 'Loading live data…' }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={21} className="spin" />
      <span>{label}</span>
    </div>
  )
}

function EmptyState({ title, detail, icon: Icon = Package }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Icon size={23} /></span>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

function ErrorState({ error, onRetry }) {
  return (
    <div className="error-state" role="alert">
      <div className="error-copy">
        <CircleAlert size={18} />
        <div>
          <strong>{error?.code || 'API_ERROR'}</strong>
          <span>{error?.message || 'Could not load data from DealerDesk.'}</span>
        </div>
      </div>
      {onRetry && <button className="button button-light button-small" onClick={onRetry}><RefreshCw size={14} /> Retry</button>}
    </div>
  )
}

function Pagination({ page, count, pageSize = PAGE_SIZE, onPageChange }) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (pages <= 1) return null
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, count)
  return (
    <div className="pagination">
      <span>Showing <b>{start}–{end}</b> of <b>{count}</b></span>
      <div className="pagination-actions">
        <button aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16} /></button>
        <span className="page-count">{page} / {pages}</span>
        <button aria-label="Next page" disabled={page >= pages} onClick={() => onPageChange(page + 1)}><ChevronRight size={16} /></button>
      </div>
    </div>
  )
}

function MetricCard({ icon: Icon, label, value, caption, tone }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}><Icon size={19} strokeWidth={2} /></div>
      <div className="metric-caption">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-footnote"><span className="live-dot" />{caption}</div>
    </article>
  )
}

function Dashboard({ products, dealers, orders, onNavigate, onOpenOrder }) {
  const openOrders = orders.filter((order) => ['CONFIRMED', 'DISPATCHED'].includes(order.status)).length
  const draftOrders = orders.filter((order) => order.status === 'DRAFT').length
  const unitsAvailable = products.reduce((total, product) => total + Number(product.stock || 0), 0)
  const categoryTotals = Object.values(products.reduce((totals, product) => {
    const category = product.category || 'Uncategorized'
    totals[category] ||= { category, units: 0, products: 0 }
    totals[category].units += Number(product.stock || 0)
    totals[category].products += 1
    return totals
  }, {})).sort((a, b) => b.units - a.units).slice(0, 5)
  const largestCategory = Math.max(1, ...categoryTotals.map((item) => item.units))
  const latestOrders = [...orders].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5)

  return (
    <div className="page-stack dashboard-page">
      <section className="welcome-panel">
        <div className="welcome-text">
          <div className="eyebrow"><span className="eyebrow-dot" /> DEALER OPERATIONS</div>
          <h2>Good day. Your business, at a glance.</h2>
          <p>Live catalogue, inventory, dealer and order data from DealerDesk.</p>
          <button className="button button-bright" onClick={() => onNavigate('orders', true)}><Plus size={16} /> Create an order</button>
        </div>
        <div className="welcome-art" aria-hidden="true">
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <div className="art-core"><Activity size={36} /></div>
          <div className="art-node node-top"><span />LIVE INVENTORY</div>
          <div className="art-node node-bottom"><span />ORDER FLOW</div>
          <div className="art-line line-a" /><div className="art-line line-b" />
        </div>
      </section>

      <section className="metric-grid" aria-label="Live summary">
        <MetricCard icon={Boxes} label="Catalogue products" value={products.length.toLocaleString('en-IN')} caption="Live product records" tone="metric-blue" />
        <MetricCard icon={Building2} label="Active dealers" value={dealers.length.toLocaleString('en-IN')} caption="Registered accounts" tone="metric-cyan" />
        <MetricCard icon={ClipboardList} label="Open orders" value={openOrders.toLocaleString('en-IN')} caption="Confirmed or dispatched" tone="metric-violet" />
        <MetricCard icon={Warehouse} label="Units available" value={unitsAvailable.toLocaleString('en-IN')} caption={`${draftOrders} draft ${draftOrders === 1 ? 'order' : 'orders'} awaiting confirmation`} tone="metric-green" />
      </section>

      <section className="dashboard-grid">
        <article className="surface-card stock-overview">
          <div className="card-heading">
            <div><div className="section-kicker">INVENTORY MIX</div><h3>Units by category</h3></div>
            <button className="icon-text-button" onClick={() => onNavigate('inventory')}>View inventory <ArrowRight size={15} /></button>
          </div>
          {categoryTotals.length === 0 ? <EmptyState title="No products yet" detail="Products will appear after the catalogue is loaded." icon={Boxes} /> : (
            <div className="category-list">
              {categoryTotals.map((item, index) => (
                <div className="category-row" key={item.category}>
                  <div className={`category-mark category-mark-${index + 1}`} />
                  <div className="category-main"><div className="category-label"><b>{item.category}</b><span>{item.products} SKUs</span></div><div className="bar-track"><div className={`bar-fill bar-fill-${index + 1}`} style={{ width: `${Math.max(3, item.units / largestCategory * 100)}%` }} /></div></div>
                  <strong className="category-units">{item.units.toLocaleString('en-IN')}</strong>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="surface-card order-overview">
          <div className="card-heading">
            <div><div className="section-kicker">LATEST ACTIVITY</div><h3>Recent orders</h3></div>
            <button className="icon-text-button" onClick={() => onNavigate('orders')}>All orders <ArrowRight size={15} /></button>
          </div>
          {latestOrders.length === 0 ? <EmptyState title="No orders yet" detail="Orders created by your team will appear here." icon={ShoppingCart} /> : (
            <div className="recent-order-list">
              {latestOrders.map((order) => {
                const dealer = dealers.find((item) => item.id === order.dealer_id)
                return (
                  <button className="recent-order" key={order.order_number} onClick={() => onOpenOrder(order.order_number)}>
                    <span className="recent-order-icon"><PackageCheck size={17} /></span>
                    <span className="recent-order-main"><b>{order.order_number}</b><small>{dealer?.name || `Dealer #${order.dealer_id}`} · {shortDate(order.created_at)}</small></span>
                    <span className="recent-order-total">{money(order.grand_total)}</span>
                    <StatusBadge status={order.status} />
                  </button>
                )
              })}
            </div>
          )}
        </article>
      </section>

      <div className="dashboard-footnote"><ShieldCheck size={15} /> All figures are read from the current DealerDesk database.</div>
    </div>
  )
}

function ProductsPage({ products, loading, error, onRetry, onNavigate }) {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [vehicle, setVehicle] = useState('')
  const [page, setPage] = useState(1)
  const [previewProduct, setPreviewProduct] = useState(null)

  const categories = [
    ...new Set(products.map((product) => product.category).filter(Boolean)),
  ].sort()

  const filtered = products.filter((product) => {
    const term = search.trim().toLowerCase()

    const matchesSearch =
      !term ||
      [product.sku, product.name, product.brand].some((value) =>
        value?.toLowerCase().includes(term)
      )

    const matchesCategory = !category || product.category === category

    const matchesVehicle =
      !vehicle.trim() ||
      product.vehicle_fitment
        ?.toLowerCase()
        .includes(vehicle.trim().toLowerCase())

    return matchesSearch && matchesCategory && matchesVehicle
  })

  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => setPage(1), [search, category, vehicle])

  return (
    <div className="page-stack">
      <PageHeading
        eyebrow="CATALOGUE"
        title="Products"
        detail="Search and inspect the live product catalogue."
        action={
          <button
            className="button button-primary"
            onClick={() => onNavigate('orders', true)}
          >
            <Plus size={16} /> Create order
          </button>
        }
      />

      <section className="surface-card data-card">
        <div className="toolbar filters-toolbar">
          <label className="search-box">
            <Search size={17} />
            <input
              aria-label="Search products"
              placeholder="Search SKU, name or brand"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          <label className="select-filter">
            <SlidersHorizontal size={16} />
            <select
              aria-label="Filter by category"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
            <ChevronDown size={15} />
          </label>

          <label className="search-box vehicle-filter">
            <input
              aria-label="Filter by vehicle fitment"
              placeholder="Vehicle fitment"
              value={vehicle}
              onChange={(event) => setVehicle(event.target.value)}
            />
          </label>

          <span className="toolbar-count">
            {filtered.length.toLocaleString('en-IN')} products
          </span>
        </div>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : filtered.length === 0 ? (
          <EmptyState
            title="No matching products"
            detail="Try changing or clearing your search and filters."
            icon={Search}
          />
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>3D Preview</th>
                    <th>SKU</th>
                    <th>Category</th>
                    <th>Brand</th>
                    <th>Vehicle fitment</th>
                    <th className="align-right">Price</th>
                    <th className="align-right">Available</th>
                  </tr>
                </thead>

                <tbody>
                  {pageRows.map((product) => (
                    <tr key={product.sku}>
                      <td>
                        <div className="product-cell">
                          <span className="table-icon">
                            <Package size={16} />
                          </span>
                          <span>
                            <b>{product.name}</b>
                            <small>{product.description || '—'}</small>
                          </span>
                        </div>
                      </td>

                      <td>
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => setPreviewProduct(product)}
                        >
                          <Eye size={14} /> View 3D
                        </button>
                      </td>

                      <td><code className="sku-code">{product.sku}</code></td>
                      <td>{product.category}</td>
                      <td>{product.brand}</td>
                      <td>{product.vehicle_fitment}</td>
                      <td className="align-right price-cell">
                        {money(product.price)}
                      </td>
                      <td className="align-right">
                        <StockValue stock={product.stock} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              page={page}
              count={filtered.length}
              onPageChange={setPage}
            />
          </>
        )}
      </section>

      {previewProduct && (
        <Modal
          title={`Product Preview - ${previewProduct.name}`}
          onClose={() => setPreviewProduct(null)}
          wide
        >
          <div style={{ padding: '12px' }}>
            <Product3DViewer product={previewProduct} />
          </div>
        </Modal>
      )}

    </div>
  )
}


function StockValue({ stock }) {
  const amount = Number(stock)
  const className = amount === 0 ? 'stock-zero' : amount <= 10 ? 'stock-low' : 'stock-normal'
  return <span className={`stock-value ${className}`}>{Number.isFinite(amount) ? amount.toLocaleString('en-IN') : '—'}</span>
}

function InventoryPage({ products, loading, error, onRetry, onStockSaved }) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const filtered = products.filter((product) => [product.sku, product.name, product.brand, product.vehicle_fitment].some((value) => value?.toLowerCase().includes(query.trim().toLowerCase())))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  useEffect(() => setPage(1), [query])

  return (
    <div className="page-stack">
      <PageHeading eyebrow="STOCK CONTROL" title="Inventory" detail="Available stock reflects current database quantities. Adjustments set an exact count." />
      <section className="surface-card data-card">
        <div className="toolbar"><label className="search-box"><Search size={17} /><input aria-label="Search inventory" placeholder="Search SKU, product, brand or vehicle" value={query} onChange={(event) => setQuery(event.target.value)} /></label><span className="toolbar-count">{filtered.length.toLocaleString('en-IN')} stock records</span></div>
        {loading ? <LoadingState /> : error ? <ErrorState error={error} onRetry={onRetry} /> : filtered.length === 0 ? <EmptyState title="No inventory records" detail="No products match that search." icon={Warehouse} /> : (
          <><div className="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th>Vehicle fitment</th><th className="align-right">Price</th><th className="align-right">Available units</th><th className="align-right">Action</th></tr></thead><tbody>
            {pageRows.map((product) => <tr key={product.sku}><td><div className="product-cell"><span className="table-icon"><Warehouse size={16} /></span><span><b>{product.name}</b><small>{product.category} · {product.brand}</small></span></div></td><td><code className="sku-code">{product.sku}</code></td><td>{product.vehicle_fitment}</td><td className="align-right price-cell">{money(product.price)}</td><td className="align-right"><StockValue stock={product.stock} /></td><td className="align-right"><button className="button button-light button-small" onClick={() => setSelected(product)}>Set stock</button></td></tr>)}
          </tbody></table></div><Pagination page={page} count={filtered.length} onPageChange={setPage} /></>
        )}
      </section>
      {selected && <StockDialog product={selected} onClose={() => setSelected(null)} onSaved={(sku, quantity) => { setSelected(null); onStockSaved(sku, quantity) }} />}
    </div>
  )
}

function StockDialog({ product, onClose, onSaved }) {
  const [quantity, setQuantity] = useState(String(product.stock))
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  async function submit(event) {
    event.preventDefault()
    if (!/^\d+$/.test(quantity) || !reason.trim()) {
      setError(new ApiError('Enter a whole quantity of zero or more and a reason.', 'VALIDATION_ERROR'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await apiRequest(`/inventory/${encodeURIComponent(product.sku)}/`, {
        method: 'PUT',
        body: { quantity: Number(quantity), reason: reason.trim() },
      })
      onSaved(result.sku, result.quantity)
    } catch (caught) {
      setError(caught)
    } finally {
      setSaving(false)
    }
  }
  return <Modal title="Set available stock" onClose={onClose}>
    <form className="dialog-form" onSubmit={submit}>
      <div className="modal-product"><span className="table-icon"><Package size={17} /></span><span><b>{product.name}</b><small>{product.sku} · current {product.stock} units</small></span></div>
      <label className="field-label">New quantity<input autoFocus type="number" min="0" step="1" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
      <label className="field-label">Reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="e.g. cycle count correction" /></label>
      {error && <InlineError error={error} />}
      <div className="dialog-actions"><button type="button" className="button button-light" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={saving}>{saving ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Save quantity</button></div>
    </form>
  </Modal>
}

function DealersPage({ dealers, loading, error, onRetry }) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const filtered = dealers.filter((dealer) => [dealer.dealer_code, dealer.name, dealer.city, dealer.phone, dealer.email].some((value) => value?.toLowerCase().includes(query.trim().toLowerCase())))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  useEffect(() => setPage(1), [query])

  return (
    <div className="page-stack">
      <PageHeading eyebrow="CUSTOMER DIRECTORY" title="Dealers" detail="Registered dealer accounts and contact details." />
      <section className="surface-card data-card">
        <div className="toolbar"><label className="search-box"><Search size={17} /><input aria-label="Search dealers" placeholder="Search name, code, city or contact" value={query} onChange={(event) => setQuery(event.target.value)} /></label><span className="toolbar-count">{filtered.length.toLocaleString('en-IN')} dealers</span></div>
        {loading ? <LoadingState /> : error ? <ErrorState error={error} onRetry={onRetry} /> : filtered.length === 0 ? <EmptyState title="No dealers found" detail="Try a different dealer name, code or city." icon={Building2} /> : (
          <><div className="table-wrap"><table><thead><tr><th>Dealer</th><th>City</th><th>Phone</th><th>Email</th><th>GSTIN</th><th className="align-right">Credit limit</th></tr></thead><tbody>
            {pageRows.map((dealer) => <tr key={dealer.id}><td><div className="dealer-cell"><span className="dealer-avatar">{initials(dealer.name)}</span><span><b>{dealer.name}</b><small>{dealer.dealer_code}</small></span></div></td><td>{dealer.city || '—'}</td><td>{dealer.phone || '—'}</td><td>{dealer.email || '—'}</td><td><code className="gstin-code">{dealer.gstin || '—'}</code></td><td className="align-right price-cell">{money(dealer.credit_limit)}</td></tr>)}
          </tbody></table></div><Pagination page={page} count={filtered.length} onPageChange={setPage} /></>
        )}
      </section>
    </div>
  )
}

function OrdersPage({ orders, dealers, loading, error, onRetry, onOpenOrder, onAction, onCreateOrder }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const filtered = orders.filter((order) => {
    const dealerName = dealers.find((dealer) => dealer.id === order.dealer_id)?.name || ''
    const matchesQuery = !query.trim() || `${order.order_number} ${dealerName} ${order.dealer_id}`.toLowerCase().includes(query.trim().toLowerCase())
    return matchesQuery && (!status || order.status === status)
  })
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  useEffect(() => setPage(1), [query, status])
  const actions = {
    DRAFT: [{ action: 'confirm', label: 'Confirm', icon: BadgeCheck }, { action: 'cancel', label: 'Cancel', icon: X }],
    CONFIRMED: [{ action: 'dispatch', label: 'Dispatch', icon: Truck }, { action: 'cancel', label: 'Cancel', icon: X }],
    DISPATCHED: [{ action: 'deliver', label: 'Deliver', icon: Check }],
  }

  return (
    <div className="page-stack">
      <PageHeading eyebrow="FULFILMENT" title="Orders" detail="Drafts, confirmations and deliveries in one place." action={<button className="button button-primary" onClick={onCreateOrder}><Plus size={16} /> New order</button>} />
      <section className="surface-card data-card">
        <div className="toolbar filters-toolbar"><label className="search-box"><Search size={17} /><input aria-label="Search orders" placeholder="Search order number or dealer" value={query} onChange={(event) => setQuery(event.target.value)} /></label><label className="select-filter"><SlidersHorizontal size={16} /><select aria-label="Filter orders by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{['DRAFT','CONFIRMED','DISPATCHED','DELIVERED','CANCELLED'].map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select><ChevronDown size={15} /></label><span className="toolbar-count">{filtered.length.toLocaleString('en-IN')} orders</span></div>
        {loading ? <LoadingState /> : error ? <ErrorState error={error} onRetry={onRetry} /> : filtered.length === 0 ? <EmptyState title="No orders yet" detail="Create a draft order to begin the fulfilment flow." icon={ShoppingCart} /> : (
          <><div className="table-wrap"><table className="orders-table"><thead><tr><th>Order</th><th>Dealer</th><th>Created</th><th>Lines</th><th>Status</th><th className="align-right">Total</th><th className="align-right">Actions</th></tr></thead><tbody>
            {pageRows.map((order) => {
              const dealer = dealers.find((item) => item.id === order.dealer_id)
              return <tr key={order.order_number}><td><button className="link-button order-number" onClick={() => onOpenOrder(order.order_number)}>{order.order_number}</button></td><td><div className="table-primary">{dealer?.name || `Dealer #${order.dealer_id}`}</div><small className="subtle-cell">{dealer?.dealer_code || '—'}</small></td><td>{shortDate(order.created_at)}<small className="subtle-cell">{shortTime(order.created_at)}</small></td><td>{order.items?.length ?? 0} lines</td><td><StatusBadge status={order.status} /></td><td className="align-right price-cell">{money(order.grand_total)}</td><td className="align-right"><div className="row-actions"><button className="icon-button" title="View order" aria-label={`View ${order.order_number}`} onClick={() => onOpenOrder(order.order_number)}><Eye size={16} /></button>{(actions[order.status] || []).map(({ action, label, icon: Icon }) => <button key={action} className={`icon-button action-${action}`} title={label} aria-label={`${label} ${order.order_number}`} onClick={() => onAction(order, action)}><Icon size={16} /></button>)}</div></td></tr>
            })}
          </tbody></table></div><Pagination page={page} count={filtered.length} onPageChange={setPage} /></>
        )}
      </section>
    </div>
  )
}

function OrderComposer({ dealers, products, onClose, onCreated }) {
  const [dealerId, setDealerId] = useState(dealers[0]?.id ? String(dealers[0].id) : '')
  const [rows, setRows] = useState([{ id: crypto.randomUUID(), sku: '', quantity: '1' }])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const datalistId = 'catalogue-skus'
  function updateRow(id, field, value) {
    setRows((current) => current.map((row) => row.id === id ? { ...row, [field]: value } : row))
  }
  function addRow() {
    setRows((current) => [...current, { id: crypto.randomUUID(), sku: '', quantity: '1' }])
  }
  function removeRow(id) {
    setRows((current) => current.length > 1 ? current.filter((row) => row.id !== id) : current)
  }
  async function submit(event) {
    event.preventDefault()
    setError(null)
    if (!dealerId) {
      setError(new ApiError('Select a dealer before creating an order.', 'VALIDATION_ERROR'))
      return
    }
    const items = []
    for (const row of rows) {
      if (!row.sku || !/^\d+$/.test(row.quantity) || Number(row.quantity) < 1) {
        setError(new ApiError('Choose a product and enter a whole quantity of at least one for every line.', 'VALIDATION_ERROR'))
        return
      }
      items.push({ sku: row.sku, quantity: Number(row.quantity) })
    }
    if (new Set(items.map((item) => item.sku)).size !== items.length) {
      setError(new ApiError('A product can appear only once per order.', 'VALIDATION_ERROR'))
      return
    }
    setSaving(true)
    try {
      const result = await apiRequest('/orders/', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { dealer_id: Number(dealerId), items },
      })
      onCreated(result)
    } catch (caught) {
      setError(caught)
    } finally {
      setSaving(false)
    }
  }
  return <Modal title="Create draft order" onClose={onClose} wide>
    {dealers.length === 0 || products.length === 0 ? <EmptyState title="Order data unavailable" detail="A dealer and at least one product are required to create an order." icon={CircleAlert} /> : (
      <form className="dialog-form" onSubmit={submit}>
        <label className="field-label">Dealer<select value={dealerId} onChange={(event) => setDealerId(event.target.value)}>{dealers.map((dealer) => <option key={dealer.id} value={dealer.id}>{dealer.dealer_code} · {dealer.name}</option>)}</select></label>
        <div className="form-section-head"><div><b>Order items</b><span>Unit prices are read from the live catalogue.</span></div><button type="button" className="button button-light button-small" onClick={addRow}><Plus size={14} /> Add line</button></div>
        <datalist id={datalistId}>{products.map((product) => <option key={product.sku} value={product.sku}>{`${product.name} · ${money(product.price)} · stock ${product.stock}`}</option>)}</datalist>
        <div className="composer-lines">{rows.map((row, index) => {
          const selectedProduct = products.find((product) => product.sku === row.sku)
          return <div className="composer-line" key={row.id}><span className="line-number">{String(index + 1).padStart(2, '0')}</span><label className="field-label line-product">Product SKU<input list={datalistId} value={row.sku} onChange={(event) => updateRow(row.id, 'sku', event.target.value.trim())} placeholder="Type or select a SKU" /></label><label className="field-label line-quantity">Quantity<input type="number" min="1" step="1" value={row.quantity} onChange={(event) => updateRow(row.id, 'quantity', event.target.value)} /></label><div className="line-price"><small>Current price</small><b>{selectedProduct ? money(selectedProduct.price) : '—'}</b></div><button type="button" className="icon-button remove-line" aria-label="Remove order line" disabled={rows.length === 1} onClick={() => removeRow(row.id)}><X size={16} /></button></div>
        })}</div>
        {error && <InlineError error={error} />}
        <div className="composer-note"><ShieldCheck size={15} /><span>Creates a DRAFT only. Stock is reserved when the order is confirmed.</span></div>
        <div className="dialog-actions"><button type="button" className="button button-light" onClick={onClose}>Close</button><button className="button button-primary" disabled={saving}>{saving ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />} Create draft</button></div>
      </form>
    )}
  </Modal>
}

function OrderDetails({ orderNumber, dealers, onClose }) {
  const [order, setOrder] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    apiRequest(`/orders/${encodeURIComponent(orderNumber)}/`, { signal: controller.signal }).then(setOrder).catch((caught) => {
      if (caught.name !== 'AbortError') setError(caught)
    })
    return () => controller.abort()
  }, [orderNumber])
  const dealer = dealers.find((item) => item.id === order?.dealer_id)
  return <Modal title="Order details" onClose={onClose} wide>
    {error ? <ErrorState error={error} /> : !order ? <LoadingState label="Loading order…" /> : <div className="order-detail">
      <div className="detail-overview"><div><span className="section-kicker">ORDER NUMBER</span><h3>{order.order_number}</h3><span className="detail-dealer">{dealer?.name || `Dealer #${order.dealer_id}`}</span></div><StatusBadge status={order.status} /></div>
      <div className="detail-meta"><span><small>Created</small><b>{shortDate(order.created_at)} · {shortTime(order.created_at)}</b></span><span><small>Updated</small><b>{shortDate(order.updated_at)} · {shortTime(order.updated_at)}</b></span></div>
      <div className="table-wrap detail-table"><table><thead><tr><th>Item</th><th>SKU</th><th className="align-right">Qty</th><th className="align-right">Unit price</th><th className="align-right">Tax</th><th className="align-right">Line total</th></tr></thead><tbody>{order.items.map((item) => <tr key={item.sku}><td><b>{item.name}</b></td><td><code className="sku-code">{item.sku}</code></td><td className="align-right">{item.quantity}</td><td className="align-right">{money(item.unit_price)}</td><td className="align-right">{money(item.line_tax)}</td><td className="align-right price-cell">{money(item.line_total)}</td></tr>)}</tbody></table></div>
      <div className="totals-panel"><span>Subtotal <b>{money(order.subtotal)}</b></span><span>GST <b>{money(order.tax_total)}</b></span><span className="grand-total">Grand total <b>{money(order.grand_total)}</b></span></div>
    </div>}
  </Modal>
}

function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    function onKeyDown(event) { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className={`modal-panel ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><h3>{title}</h3><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={18} /></button></div>{children}</section></div>
}

function InlineError({ error }) {
  return <div className="inline-error" role="alert"><CircleAlert size={16} /><span><b>{error.code || 'ERROR'}</b> · {error.message}</span></div>
}

function PageHeading({ eyebrow, title, detail, action }) {
  return <div className="page-heading"><div><div className="section-kicker">{eyebrow}</div><h2>{title}</h2><p>{detail}</p></div>{action && <div className="page-heading-action">{action}</div>}</div>
}

function App() {
  const [activePage, setActivePage] = useState('dashboard')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [products, setProducts] = useState([])
  const [dealers, setDealers] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [showOrderComposer, setShowOrderComposer] = useState(false)
  const [openOrderNumber, setOpenOrderNumber] = useState(null)
  const [toast, setToast] = useState(null)

  const refresh = useCallback(() => setRefreshToken((token) => token + 1), [])
  const loadData = useCallback(async (signal) => {
    setLoading(true)
    setError(null)
    try {
      const [catalogue, dealerRows, orderRows] = await Promise.all([
        getAllPages('/products/', signal),
        getAllPages('/dealers/', signal),
        getAllPages('/orders/', signal),
      ])
      setProducts(catalogue)
      setDealers(dealerRows)
      setOrders(orderRows)
    } catch (caught) {
      if (caught.name !== 'AbortError') setError(caught)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadData(controller.signal)
    return () => controller.abort()
  }, [loadData, refreshToken])

  useEffect(() => {
    if (!toast) return undefined
    const timer = window.setTimeout(() => setToast(null), 4200)
    return () => window.clearTimeout(timer)
  }, [toast])

  function navigate(page, create = false) {
    setActivePage(page)
    setMobileMenuOpen(false)
    if (create) setShowOrderComposer(true)
  }

  async function handleStockSaved(sku, quantity) {
    setToast({ tone: 'success', message: `${sku} stock set to ${quantity}.` })
    refresh()
  }

  async function handleOrderAction(order, action) {
    const labels = { confirm: 'Confirm', dispatch: 'Dispatch', deliver: 'Deliver', cancel: 'Cancel' }
    if (action === 'cancel' && !window.confirm(`Cancel draft/confirmed order ${order.order_number}?`)) return
    try {
      const updated = await apiRequest(`/orders/${encodeURIComponent(order.order_number)}/${action}/`, { method: 'POST', body: {} })
      setOrders((current) => current.map((item) => item.order_number === order.order_number ? updated : item))
      setToast({ tone: 'success', message: `${labels[action]} successful for ${order.order_number}.` })
    } catch (caught) {
      setToast({ tone: 'error', message: `${caught.code || 'ERROR'}: ${caught.message}` })
      refresh()
    }
  }

  function handleOrderCreated(order) {
    setShowOrderComposer(false)
    setActivePage('orders')
    setOrders((current) => [order, ...current])
    setToast({ tone: 'success', message: `Draft ${order.order_number} created.` })
  }

  const selectedNavigation = NAVIGATION.find((item) => item.id === activePage) || NAVIGATION[0]
  const currentDate = new Intl.DateTimeFormat('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date())

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenuOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-lockup"><span className="brand-mark"><span /><span /><span /></span><span className="brand-text"><b>VIKMO</b><small>DEALERDESK</small></span></div>
        <div className="sidebar-caption">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {NAVIGATION.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-link ${activePage === id ? 'nav-active' : ''}`} onClick={() => navigate(id)}><Icon size={18} strokeWidth={1.9} /><span>{label}</span>{id === 'orders' && orders.length > 0 && <span className="nav-count">{orders.length}</span>}</button>)}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-health"><span className="health-indicator"><span /></span><span><b>Connected</b><small>DealerDesk API</small></span><ShieldCheck className="health-shield" size={17} /></div>
        <div className="sidebar-footer"><span>VIKMO OPERATIONS</span><span>Dealer workspace</span></div>
      </aside>

      {mobileMenuOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileMenuOpen(false)} />}

      <main className="main-shell">
        <header className="topbar">
          <div className="topbar-left"><button className="mobile-menu-button icon-button" aria-label="Open navigation" onClick={() => setMobileMenuOpen(true)}><Menu size={19} /></button><div className="breadcrumb"><span>Workspace</span><ChevronRight size={14} /><b>{selectedNavigation.label}</b></div></div>
          <div className="topbar-actions"><span className="date-display"><Clock3 size={15} />{currentDate}</span><span className="topbar-divider" /><button className="icon-button refresh-button" aria-label="Refresh live data" title="Refresh live data" onClick={refresh}><RefreshCw size={16} /></button><button className="user-chip" aria-label="DealerDesk operator"><span>VD</span><b>Operations</b><ChevronDown size={14} /></button></div>
        </header>

        <div className="content-shell">
          <div className="content-heading-row"><div className="connection-note"><span className="live-dot" /> Live database data</div>{activePage === 'dashboard' && <span className="current-context">{selectedNavigation.label} <ArrowUpRight size={14} /></span>}</div>
          {error && <ErrorState error={error} onRetry={() => loadData()} />}
          {activePage === 'dashboard' && <Dashboard products={products} dealers={dealers} orders={orders} onNavigate={navigate} onOpenOrder={setOpenOrderNumber} />}
          {activePage === 'products' && <ProductsPage products={products} loading={loading} error={error} onRetry={() => loadData()} onNavigate={navigate} />}
          {activePage === 'inventory' && <InventoryPage products={products} loading={loading} error={error} onRetry={() => loadData()} onStockSaved={handleStockSaved} />}
          {activePage === 'dealers' && <DealersPage dealers={dealers} loading={loading} error={error} onRetry={() => loadData()} />}
          {activePage === 'orders' && <OrdersPage orders={orders} dealers={dealers} loading={loading} error={error} onRetry={() => loadData()} onOpenOrder={setOpenOrderNumber} onAction={handleOrderAction} onCreateOrder={() => setShowOrderComposer(true)} />}
          <footer className="app-footer"><span>VIKMO DealerDesk</span><span>Operational view · All displayed records are API-backed</span></footer>
        </div>
      </main>

      {showOrderComposer && <OrderComposer dealers={dealers} products={products} onClose={() => setShowOrderComposer(false)} onCreated={handleOrderCreated} />}
      {openOrderNumber && <OrderDetails orderNumber={openOrderNumber} dealers={dealers} onClose={() => setOpenOrderNumber(null)} />}
      {toast && <div className={`toast toast-${toast.tone}`} role="status"><span>{toast.tone === 'success' ? <CircleCheck size={17} /> : <CircleAlert size={17} />}</span>{toast.message}<button className="toast-close" aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={15} /></button></div>}
    </div>
  )
}

export default App