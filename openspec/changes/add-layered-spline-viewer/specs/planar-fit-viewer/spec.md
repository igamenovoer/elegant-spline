# Planar fit viewer

## Purpose

Let a caller inspect how an ordered set of planar observations becomes a spline, overlaying the recorded fit and its construction on the intended spatial domain.

## ADDED Requirements

### Requirement: Portable fit documents

A caller SHALL be able to export a versioned local document from the original ordered observations, a planar fitting result and an optional polygonal domain. The viewer SHALL open a bundled example or a user-selected document in the browser and identify invalid or unsupported input before replacing the current view.

#### Scenario: Open a fit from the Python library

- **WHEN** a caller exports a result from any supported planar fitter and opens it in the standalone viewer
- **THEN** the viewer displays the recorded geometry, fit status and preprocessing in the original coordinate units
- **AND** the browser can inspect the document with the fitting process stopped.

#### Scenario: Reject an inconsistent file

- **WHEN** a user opens a document with an unsupported version or a source point mapped to a nonexistent cluster
- **THEN** the viewer identifies the version or invalid field and keeps the previously loaded document and view usable.

### Requirement: Four independently visible layers share one viewport

The viewer SHALL provide separate visibility controls for Domain, Data points, Preprocessing and Fitted curve. Available layers SHALL share an equal-scale XY coordinate system with positive Y upwards. Users SHALL be able to pan, zoom and frame the geometry. Changing a layer’s visibility SHALL preserve the viewport and the settings of the other layers.

#### Scenario: Inspect the fit at a corner

- **WHEN** a user zooms into a corner and toggles each layer in turn
- **THEN** only the chosen layer and its annotations change visibility, other geometry stays registered to the same screen position, and hidden marks cease to be pickable
- **AND** re-enabling a layer restores its selected sublayers.

### Requirement: Domain preserves the permitted region

The Domain layer SHALL show the outer ring and each hole, distinguish permitted area from excluded area, and offer a separately toggleable clearance band when a required clearance is supplied. A domain describes the intended region. A displayed fit SHALL remain inspectable where it crosses a boundary.

#### Scenario: A curve passes through a hole

- **WHEN** a document includes a polygon with a hole, a clearance distance and a curve crossing the hole
- **THEN** the hole is visibly excluded, the band extends into the permitted region along both boundaries, and the crossing segment stays visible.

#### Scenario: Fit without spatial constraints

- **WHEN** the document omits the domain
- **THEN** the viewer identifies the domain as unavailable and displays the other recorded layers.

### Requirement: Data points preserve sequence identity

The Data points layer SHALL show the original target observations in traversal order and make the index and XY coordinates of every visit inspectable, including visits at identical coordinates.

#### Scenario: Inspect coincident observations and a return visit

- **WHEN** two consecutive observations coincide and a later observation returns to that XY position
- **THEN** a user can select each of the three sequence indices and see its position in the ordered traversal.

### Requirement: Preprocessing shows the fitter’s decisions

The Preprocessing layer SHALL distinguish cluster representatives from the resampled points used by the solver. Selecting a cluster SHALL identify every original member by sequence index and highlight the visible members. Membership and representative positions SHALL reflect the recorded fitting result.

#### Scenario: Inspect one merge

- **WHEN** consecutive duplicate and nearby observations have merged into one cluster
- **THEN** the viewer shows that cluster’s reported representative, its original member indices and their relationship to the representative
- **AND** the resampled solver points can be distinguished even where they coincide with a representative.

### Requirement: Curve construction is inspectable

The Fitted curve layer SHALL provide independent controls for the curve stroke, native B-spline control points with their control polygon, and cubic Bézier handles with their anchor lines. The stroke and handles SHALL represent the same spline over each nonzero knot span. Controls and handles SHALL be selectable for inspection by index or span and XY position.

#### Scenario: Inspect the handles at a knot

- **WHEN** a user inspects the join between two unequal-width cubic spans
- **THEN** the incoming and outgoing handles are anchored at the evaluated knot position and correspond to the respective spans
- **AND** hiding the control polygon and its points leaves the visible handles and curve stroke in place.

#### Scenario: Switch curve stages

- **WHEN** the document contains initial, pre-fairing and final geometry and the user changes the selected stage
- **THEN** the stroke, controls and handles come from the selected stage, and the other layers and viewport retain their state.

### Requirement: Fit outcomes remain distinguishable

The viewer SHALL distinguish a fitted curve, a fallback curve and an unavailable result. The source and preprocessing layers SHALL remain inspectable for each outcome.

#### Scenario: Inspect a degenerate fallback

- **WHEN** the recorded fallback is a line or a constant
- **THEN** the viewer identifies it as a fallback and allows its geometry to be framed and inspected, including coincident controls

#### Scenario: Open a result with no curve

- **WHEN** a user opens an unavailable result after viewing a successful fit
- **THEN** the viewer clears the previous curve, controls and handles and shows the recorded reason and the new observations.
