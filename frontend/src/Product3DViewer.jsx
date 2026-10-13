
import { useState, useEffect, useRef } from "react";
import "@google/model-viewer";

export default function Product3DViewer({ product }) {
  const [activeTab, setActiveTab] = useState("photo");
  const [zoom, setZoom] = useState(1);
  const [imageError, setImageError] = useState(false);
  const viewerRef = useRef(null);

  const imageUrl =
    product?.image_url ||
    product?.image ||
    product?.imageUrl ||
    product?.photo_url ||
    product?.photo ||
    "";

  const modelUrl =
    product?.model_3d_url ||
    product?.modelUrl ||
    product?.glb_url ||
    "";

  const productName = product?.name || "Product";
  const sku = product?.sku || "—";

  useEffect(() => {
    setZoom(1);
    setImageError(false);
    setActiveTab("photo");
  }, [sku]);

  const buttonStyle = {
    padding: "9px 14px",
    borderRadius: "8px",
    border: "1px solid #0891b2",
    background: "#164e63",
    color: "#ffffff",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 600,
  };

  const activeButtonStyle = {
    ...buttonStyle,
    background: "#0891b2",
    color: "#ffffff",
  };

  async function openFullscreen() {
    const element = viewerRef.current;

    if (!element) return;

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (element.requestFullscreen) {
        await element.requestFullscreen();
      }
    } catch (error) {
      console.error("Fullscreen could not be opened:", error);
    }
  }

  return (
    <div style={{ color: "#e2e8f0", width: "100%" }}>
      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: "10px",
          flexWrap: "wrap",
          marginBottom: "14px",
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("photo")}
          style={activeTab === "photo" ? activeButtonStyle : buttonStyle}
        >
          Product Photo
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("3d")}
          style={activeTab === "3d" ? activeButtonStyle : buttonStyle}
        >
          Interactive 3D
        </button>
      </div>

      {/* Product viewer */}
      <div
        ref={viewerRef}
        style={{
          width: "100%",
          height: "420px",
          background: "#0b1220",
          borderRadius: "16px",
          overflow: "hidden",
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {activeTab === "photo" ? (
          imageUrl && !imageError ? (
            <img
              key={imageUrl}
              src={imageUrl}
              alt={productName}
              onError={() => setImageError(true)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "contain",
                transform: `scale(${zoom})`,
                transition: "transform 0.25s ease",
              }}
            />
          ) : (
            <div
              style={{
                textAlign: "center",
                padding: "24px",
                maxWidth: "360px",
              }}
            >
              <div style={{ fontSize: "52px", marginBottom: "12px" }}>
                📦
              </div>

              <h3 style={{ margin: "0 0 10px", color: "#f1f5f9" }}>
                Product photo unavailable
              </h3>

              <p style={{ color: "#94a3b8", fontSize: "14px" }}>
                Please add a valid image URL for this product.
              </p>
            </div>
          )
        ) : modelUrl ? (
          <model-viewer
            key={modelUrl}
            src={modelUrl}
            alt={`${productName} 3D model`}
            camera-controls
            auto-rotate
            shadow-intensity="1"
            exposure="1"
            environment-image="neutral"
            loading="eager"
            style={{
              width: "100%",
              height: "100%",
              backgroundColor: "#0b1220",
            }}
          />
        ) : (
          <div
            style={{
              textAlign: "center",
              padding: "24px",
              maxWidth: "360px",
            }}
          >
            <div style={{ fontSize: "52px", marginBottom: "12px" }}>
              🧊
            </div>

            <h3 style={{ margin: "0 0 10px", color: "#f1f5f9" }}>
              3D model unavailable
            </h3>

            <p style={{ color: "#94a3b8", fontSize: "14px" }}>
              Please add a valid image URL for this product.
            </p>
          </div>
        )}

        {/* Viewer label */}
        <div
          style={{
            position: "absolute",
            top: "12px",
            left: "12px",
            padding: "7px 10px",
            borderRadius: "7px",
            background: "#164e63",
            color: "#a5f3fc",
            fontSize: "11px",
            fontWeight: 700,
            pointerEvents: "none",
          }}
        >
          {activeTab === "photo" ? "PRODUCT IMAGE" : "3D MODEL"}
        </div>
      </div>

      {/* Viewer controls */}
      <div
        style={{
          display: "flex",
          gap: "8px",
          flexWrap: "wrap",
          marginTop: "12px",
        }}
      >
        {activeTab === "photo" && (
          <>
            <button
              type="button"
              style={buttonStyle}
              onClick={() =>
                setZoom((value) => Math.max(1, value - 0.2))
              }
            >
              − Zoom
            </button>

            <button
              type="button"
              style={buttonStyle}
              onClick={() =>
                setZoom((value) => Math.min(2.5, value + 0.2))
              }
            >
              + Zoom
            </button>

            <button
              type="button"
              style={buttonStyle}
              onClick={() => setZoom(1)}
            >
              Reset
            </button>
          </>
        )}

        <button
          type="button"
          style={buttonStyle}
          onClick={openFullscreen}
        >
          Fullscreen
        </button>
      </div>

      {/* Product details: one copy only inside this component */}
      <div
        style={{
          marginTop: "20px",
          padding: "16px",
          borderRadius: "12px",
          background: "#111827",
          lineHeight: 1.9,
          overflowWrap: "anywhere",
        }}
      >
        <div>
          <strong>Product:</strong> {productName}
        </div>

        <div>
          <strong>SKU:</strong> {sku}
        </div>

        <div>
          <strong>Category:</strong>{" "}
          {product?.category || "Not specified"}
        </div>

        <div>
          <strong>Brand:</strong>{" "}
          {product?.brand || "Not specified"}
        </div>

        <div>
          <strong>Price:</strong>{" "}
          {product?.price ?? "Not specified"}
        </div>
      </div>
    </div>
  );
}
